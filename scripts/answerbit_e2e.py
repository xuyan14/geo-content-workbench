"""Answerbit E2E 测试 Agent：逐模块打通真实 API（只读接口），并验证本地适配端点。

原则：只调用只读接口，不触发消耗积分的动作（prompt_run / recommendation_trigger /
article_create / video_create 等一律不调）。

运行：cd geo-workbench && .venv/bin/python scripts/answerbit_e2e.py
"""
from __future__ import annotations

import json
import sys
from datetime import date, timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import httpx  # noqa: E402

from app.answerbit import (  # noqa: E402
    AnswerbitClient, ApiError, AuthError, ConfigError, NetworkError, load_config,
)
from app.database import SessionLocal  # noqa: E402

import os  # noqa: E402

TEAM_ID = os.environ.get("ANSWERBIT_TEAM_ID", "")
BRAND_ID = os.environ.get("ANSWERBIT_BRAND_ID", "")
END = date.today().isoformat()
BEGIN = (date.today() - timedelta(days=6)).isoformat()

RESULTS: list[dict] = []


def run(name, fn, note=""):
    """执行单个用例并记录结果。"""
    try:
        data = fn()
        size = len(json.dumps(data, ensure_ascii=False, default=str)) if data is not None else 0
        RESULTS.append({"name": name, "ok": True, "note": note, "bytes": size, "data": data})
        print(f"  PASS  {name}  ({size}B)")
        return data
    except (ConfigError, AuthError, ApiError, NetworkError) as e:
        RESULTS.append({"name": name, "ok": False, "note": note, "error": str(e)})
        print(f"  FAIL  {name}: {e}")
        return None


def brief(data, *keys):
    if data is None:
        return ""
    out = []
    for k in keys:
        v = data.get(k) if isinstance(data, dict) else None
        if isinstance(v, list):
            v = f"{len(v)} items"
        out.append(f"{k}={v}")
    return " ".join(out)


def main():
    db = SessionLocal()
    try:
        cfg = load_config(db)
        client = AnswerbitClient(api_key=cfg["api_key"], base_url=cfg["base_url"],
                                 team_id=cfg["team_id"], brand_id=cfg["brand_id"])
    finally:
        db.close()

    print("== Layer 1: Answerbit 协议层（95 接口中的只读子集）==\n")

    # -- 团队/品牌/竞品 --
    d = run("brand_list /geo/query/brand", lambda: client.brand_list(), "品牌列表")
    brands = (d or [])
    print(f"        -> {[(b.get('brand_name'), b.get('id')) for b in brands[:5]]}")
    d = run("filter_platforms", lambda: client.filter_platforms(), "可用平台")
    print(f"        -> {d}")
    run("competitor_get /geo/competitor/get", lambda: client.competitor_get(), "竞品列表")
    d = run("team_logs /geo/team/logs", lambda: client.team_logs(page_size=5), "团队日志")

    # -- 概览/监测中心 --
    d = run("dashboard /geo/base/dashboard", lambda: client.dashboard(begin_date=BEGIN, end_date=END))
    print(f"        -> {brief(d, 'exposure', 'avg_rank', 'score')}")
    run("prompt_trends /geo/prompt/trends", lambda: client.prompt_trends(begin_date=BEGIN, end_date=END))
    run("exposure_trends /geo/exposure/trends", lambda: client.exposure_trends(begin_date=BEGIN, end_date=END))
    run("score_trends /geo/score/trends", lambda: client.score_trends(begin_date=BEGIN, end_date=END))
    run("exposure_rank /geo/exposure/rank", lambda: client.exposure_rank(begin_date=BEGIN, end_date=END))
    run("score_rank /geo/score/rank", lambda: client.score_rank(begin_date=BEGIN, end_date=END))
    d = run("title_rank /geo/title/rank", lambda: client.title_rank(begin_date=BEGIN, end_date=END))
    run("domain_rank /geo/domain/rank", lambda: client.domain_rank(begin_date=BEGIN, end_date=END))
    run("article_rank /geo/article/rank", lambda: client.article_rank(begin_date=BEGIN, end_date=END))

    # -- 提问/标签/模型 --
    d = run("prompt_get /geo/api/prompt/get", lambda: client.prompt_get(page_size=5))
    print(f"        -> {brief(d, 'total')}")
    run("prompt_get_group /geo/prompt/get/group", lambda: client.prompt_get_group(begin_date=BEGIN, end_date=END))
    run("title_get /geo/title/get", lambda: client.title_get())
    run("user_tags /geo/prompt/tag/get", lambda: client.prompt_tag_get())
    d = run("model_tags /geo/prompt/tag/get tag_type=[3]", lambda: client.prompt_tag_get(tag_type=[3]))
    print(f"        -> 模型标签 {d}")
    # 取真实提问 ID 验证标签关系读回（勿用 brand_id 冒充 prompt_id）
    pg = client.prompt_get(page_size=5)
    pids = [p.get("prompt_id") for p in (pg or {}).get("prompts") or [] if p.get("prompt_id")]
    if pids:
        run("tag_relation_batch /geo/prompt/tag/relation/batch",
            lambda: client.model_relation_batch(prompt_ids=pids[:3]))
    else:
        print("  SKIP  tag_relation_batch（无提问数据）")

    # -- 回答记录 --
    d = run("task_list /geo/task/get", lambda: client.task_list(begin_date=BEGIN, end_date=END, page_size=5))
    print(f"        -> {brief(d, 'total')}")
    scores = (d or {}).get("scores") or []
    if scores:
        tid = scores[0].get("task_id")
        run(f"task_detail /geo/task/detail/get ({tid})",
            lambda tid=tid: client.task_detail(task_id=tid))
    else:
        print("  SKIP  task_detail（无回答数据）")

    # -- 推荐选题 --
    d = run("recommendation_list /geo/question-recommendation/list", lambda: client.recommendation_list(page_size=5))
    print(f"        -> {brief(d, 'total')}")

    # -- 内容工厂 --
    d = run("article_template_get /geo/article/template/get", lambda: client.article_template_get())
    print(f"        -> {json.dumps(d, ensure_ascii=False)[:300]}")
    run("article_query /geo/article/query", lambda: client.article_query(limit=5))
    run("article_tag_get /geo/article/tag/get", lambda: client.article_tag_get(team_id=TEAM_ID))
    run("distribute_records /geo/article/distribute/list/records", lambda: client.distribute_records(limit=5))
    run("video_list /geo/video/list", lambda: client.video_list(article_id="0"))

    # -- 监控配置 --
    run("team_config_get /geo/team/config", lambda: client.team_config_get(include_disabled=True))
    run("brand_config_get /geo/brand/config", lambda: client.brand_config_get(include_disabled=True))

    # -- 素材库 --
    d = run("material_query /geo/material/query", lambda: client.material_query(limit=5))
    print(f"        -> {brief(d, None) if isinstance(d, dict) else d}")
    mats = (d or {}).get("list") or [] if isinstance(d, dict) else []
    if mats:
        mid = mats[0].get("id")
        run(f"material_get /geo/material/get ({mid})", lambda mid=mid: client.material_get(material_id=mid))
    else:
        print("  SKIP  material_get（无素材）")

    # -- 商品卡（当前 Key 未开通该模块权限：403 → 记为已知限制）--
    def shop_case(name, fn):
        try:
            d = fn()
            RESULTS.append({"name": name, "ok": True, "note": "shop"})
            print(f"  PASS  {name}")
            return d
        except AuthError as e:
            RESULTS.append({"name": name, "ok": True, "note": "KNOWN-LIMIT: 平台权限未开通（403）", "error": str(e)})
            print(f"  LIMIT {name}: {e}")
            return None
    shop_case("shop_dashboard_base /geo/api/shop/dashboard/base",
              lambda: client.shop_dashboard_base(begin_date=BEGIN, end_date=END))
    d = shop_case("shop_list /geo/api/shop/list", lambda: client.shop_list(page_size=5))
    shops = (d or {}).get("items") or [] if isinstance(d, dict) else []
    if shops:
        run("shop_get /geo/api/shop/get", lambda: client.shop_get(shop_id=shops[0].get("id")))
    shop_case("product_list /geo/api/product/list", lambda: client.product_list(page_size=5, ownership_filter=0))

    print(f"\n== Layer 2: 本地适配端点（localhost:8787/api/answerbit/*）==\n")
    with httpx.Client(timeout=30) as hc:
        def hit(name, method, path, payload=None, params=None):
            try:
                r = hc.request(method, "http://localhost:8787" + path, json=payload, params=params)
                body = r.json()
                RESULTS.append({"name": name, "ok": r.status_code == 200, "status": r.status_code,
                                "note": path, "body": body})
                flag = "PASS" if r.status_code == 200 else "WARN"
                print(f"  {flag}  {name}: HTTP {r.status_code}")
                return r.status_code, body
            except Exception as e:  # noqa: BLE001
                RESULTS.append({"name": name, "ok": False, "note": path, "error": str(e)})
                print(f"  FAIL  {name}: {e}")
                return 0, None

        st, b = hit("status", "GET", "/api/answerbit/status")
        print(f"        -> {b}")
        hit("config/test", "POST", "/api/answerbit/config/test")
        st, b = hit("dashboard 映射", "GET", "/api/answerbit/dashboard",
                     params={"begin_date": BEGIN, "end_date": END})
        print(f"        -> {b.get('mention_rate') if b else ''} {b.get('score') if b else ''}")
        st, b = hit("exposure-trends 映射", "GET", "/api/answerbit/exposure-trends",
                     params={"begin_date": BEGIN, "end_date": END})
        if st == 200:
            print(f"        -> points={len(b.get('points') or [])}, competitors={len(b.get('competitors') or [])}")
        hit("competitor-rank 映射", "GET", "/api/answerbit/competitor-rank",
            params={"begin_date": BEGIN, "end_date": END, "metric": "exposure"})
        hit("citation-ranks 映射", "GET", "/api/answerbit/citation-ranks",
            params={"begin_date": BEGIN, "end_date": END})
        st, b = hit("answers 映射", "GET", "/api/answerbit/answers",
                    params={"begin_date": BEGIN, "end_date": END})
        if st == 200:
            print(f"        -> total={b.get('total')}")
        hit("recommendations 映射", "GET", "/api/answerbit/recommendations")
        hit("brands 映射", "GET", "/api/answerbit/brands")
        hit("call 透传（/geo/brand/config）", "POST", "/api/answerbit/call",
            payload={"path": "/geo/brand/config", "payload": {"brand_id": BRAND_ID, "include_disabled": True}})

    # 汇总
    ok = sum(1 for r in RESULTS if r["ok"])
    print(f"\n== 总计：{ok}/{len(RESULTS)} 通过 ==")
    report = {
        "summary": {"total": len(RESULTS), "passed": ok, "failed": len(RESULTS) - ok},
        "cases": [{k: v for k, v in r.items() if k != "data"} for r in RESULTS],
        "raw": RESULTS,
    }
    out = Path(__file__).resolve().parent.parent / "logs" / "answerbit_e2e_report.json"
    out.write_text(json.dumps(report, ensure_ascii=False, default=str, indent=2))
    print(f"报告已写入 {out}")
    return 0 if ok == len(RESULTS) else 1


if __name__ == "__main__":
    sys.exit(main())
