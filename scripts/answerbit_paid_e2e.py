"""消耗积分类接口 E2E（用户授权小预算测试）。

Step 1  prompt_run          1 提问 × deepseek × run_count=1  预计 20 积分
Step 2  article_create      模板 2 + 1 提问，轮询生成结果
Step 3  recommendation_trigger  触发推荐选题生成，观察列表变化

运行：.venv/bin/python scripts/answerbit_paid_e2e.py <step:1|2|3|all>
"""
from __future__ import annotations

import json
import sys
import time
from datetime import date
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.answerbit import (  # noqa: E402
    AnswerbitClient, ApiError, AuthError, ConfigError, NetworkError,
)
from app.database import SessionLocal  # noqa: E402

PROMPT_ID = "2112156422459367428"  # 江南布衣羽绒服哪里买保真又划算？（已启用）
TODAY = date.today().isoformat()


def get_c() -> AnswerbitClient:
    db = SessionLocal()
    try:
        from app.answerbit import load_config
        cfg = load_config(db)
        return AnswerbitClient(api_key=cfg["api_key"], base_url=cfg["base_url"],
                              team_id=cfg["team_id"], brand_id=cfg["brand_id"])
    finally:
        db.close()


def poll(fn, want, interval=15, max_s=180, desc=""):
    """轮询直至 want(data) 为真或超时，返回 (data, used_s)。"""
    t0 = time.time()
    while True:
        try:
            data = fn()
            if want(data):
                return data, round(time.time() - t0, 1)
        except (ApiError, AuthError, NetworkError) as e:
            print(f"      轮询异常（继续）：{e}")
        if time.time() - t0 > max_s:
            return None, round(time.time() - t0, 1)
        time.sleep(interval)
        print(f"      ...等待{desc}（{int(time.time() - t0)}s）")


def step1_prompt_run(c: AnswerbitClient):
    print("== Step 1: prompt_run（1 提问 × deepseek × 1 次，预计 20 积分）==")
    baseline = c.task_list(begin_date=TODAY, end_date=TODAY,
                           prompt_ids=[PROMPT_ID], include_unanalyzed=True, page_size=50)
    base_ids = {s.get("task_id") for s in (baseline or {}).get("scores") or []}
    print(f"  今日该提问已有 {len(base_ids)} 个任务")
    r = c.prompt_run(prompt_ids=[PROMPT_ID], run_count=1, platforms=["deepseek"])
    print(f"  受理成功：{r}")

    def fetch():
        return c.task_list(begin_date=TODAY, end_date=TODAY,
                           prompt_ids=[PROMPT_ID], include_unanalyzed=True, page_size=50)

    def has_new(d):
        return bool({s.get("task_id") for s in (d or {}).get("scores") or []} - base_ids)

    data, used = poll(fetch, has_new, interval=15, max_s=180, desc="新任务出现")
    if not data:
        print(f"  [超时] 3 分钟内未见新任务（可能排队中，稍后可用 task_list 复查）")
        return False
    new = [s for s in data.get("scores") or [] if s.get("task_id") not in base_ids]
    print(f"  新任务出现（{used}s）：")
    for s in new[:3]:
        print(f"    task_id={s.get('task_id')} platform={s.get('platform')} "
              f"exposure={s.get('exposure')} score={s.get('score')} rank={s.get('avg_rank')} "
              f"analysis={((s.get('analysis') or {}).get('state'))}")
    tid = new[0].get("task_id")
    # 等分析完成再取详情
    def analyzed(d):
        row = [s for s in (d or {}).get("scores") or [] if s.get("task_id") == tid]
        st = (row[0].get("analysis") or {}).get("state") if row else 0
        return st in (2, 3, 4)

    d2, used2 = poll(fetch, analyzed, interval=15, max_s=180, desc="分析完成")
    try:
        detail = c.task_detail(task_id=tid)
        print(f"  回答详情（分析等待 {used2}s）：")
        print(f"    问题：{detail.get('prompt') or detail.get('query')}")
        print(f"    引擎：{detail.get('platform')} | 提及：{detail.get('exposure')} | "
              f"排名：{detail.get('rank')} | 评分：{detail.get('score')}")
        print(f"    引用链接：{[l.get('url') for l in (detail.get('links') or [])[:3]]}")
        out = (detail.get("llm_output") or "")[:200].replace("\n", " ")
        print(f"    回答原文（前 200 字）：{out}")
        Path("logs").mkdir(exist_ok=True)
        with open("logs/answerbit_task_detail.json", "w") as f:
            json.dump(detail, f, ensure_ascii=False, indent=2)
        return True
    except (ApiError, AuthError, NetworkError) as e:
        print(f"  详情获取失败：{e}")
        return False


def step2_article_create(c: AnswerbitClient):
    print("== Step 2: article_create（模板 2 + 1 提问，异步生成）==")
    r = c.article_create(template_type="2", prompt_ids=[PROMPT_ID], language="zh-CN")
    print(f"  受理成功：{r}")
    aid = (r or {}).get("id") or (r or {}).get("article_id")
    if not aid:
        print(f"  [注意] 响应中无文章 ID，无法轮询：{r}")
        return False
    data, used = poll(lambda: c.article_get(article_id=aid),
                     lambda d: d is not None and int((d or {}).get("status", 0) or 0) != 0,
                     interval=20, max_s=300, desc="文章生成完成")
    if not data:
        print(f"  [超时] 5 分钟内未生成完成")
        return False
    status = int(data.get("status", 0))
    labels = {0: "生成中", 1: "待发布", 2: "发布中", 3: "追踪中", 4: "失败"}
    print(f"  生成完成（{used}s）：status={status}（{labels.get(status)}）")
    print(f"    标题：{data.get('title')}")
    body = (data.get("main_body") or data.get("body") or "")[:300].replace("\n", " ")
    print(f"    正文前 300 字：{body}")
    with open("logs/answerbit_article.json", "w") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
    return status in (1, 2, 3)


def step3_recommendation_trigger(c: AnswerbitClient):
    print("== Step 3: recommendation_trigger（触发推荐选题生成）==")
    before = c.recommendation_list(page_size=1)
    base_total = (before or {}).get("total")
    print(f"  当前推荐选题总数：{base_total}")
    r = c.recommendation_trigger(target_date=TODAY)
    print(f"  触发成功：{r}")
    data, used = poll(lambda: c.recommendation_list(page_size=1),
                      lambda d: (d or {}).get("total") not in (None, base_total),
                      interval=10, max_s=120, desc="推荐列表变化")
    after = c.recommendation_list(page_size=3)
    print(f"  推荐选题最新 total={after.get('total')}（等待 {used}s）")
    for it in (after.get("list") or [])[:3]:
        print(f"    [{it.get('status')}] {(it.get('question_text') or '')[:50]} heat={it.get('heat_score')}")
    return True


def main():
    step = sys.argv[1] if len(sys.argv) > 1 else "all"
    c = get_c()
    ok = True
    if step in ("1", "all"):
        ok = step1_prompt_run(c) and ok
    if step in ("2", "all"):
        ok = step2_article_create(c) and ok
    if step in ("3", "all"):
        ok = step3_recommendation_trigger(c) and ok
    print(f"\n== 完成（step={step}）：{'全部通过' if ok else '存在失败项，见上方输出'} ==")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
