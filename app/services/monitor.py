"""监测中心：多引擎采样 + 品牌提及判定（借鉴 GeoLook sample.py 的规则引擎）。

提及判定纯正则/规则，不用 LLM 判读（口径可复现）：
- 别名匹配：拉丁字符加边界，防「AIGC」误命中「AIGCLINK」；纯 CJK 用子串
- 否定语境：提及前 20 字出现「不是/并非/排除」→ 不算提及但标 needs_review
- 负面线索：首次提及 ±80/160 字符窗口内的保守负面词 → 标「疑似负面」待人工复核
- 排名：品牌与竞品按首次出现位置排序，品牌所在位次
- 点名品牌的问题只算品牌认知，不进可见性指标
"""
import json
import re
import threading
from datetime import datetime
from typing import List, Optional
from urllib.parse import urlparse

from ..ai.client import LLMClient
from ..database import SessionLocal
from ..models import Brand, MonitorQuery, MonitorRun, MonitorSample

NEG_CUES = [
    "不推荐", "避雷", "骗局", "智商税", "慎入", "差评", "翻车", "割韭菜",
    "投诉无门", "跑路", "虚假宣传", "夸大宣传", "退款难",
]
NEGATION_RE = re.compile(r"(不是|并非|不包括|排除|谈不上|不算)")

SAMPLING_SYSTEM = (
    "你是一个知识渊博、客观中立的 AI 助手。请直接、完整地回答用户的问题，"
    "如引用来源请附上原文链接。不要拒绝回答，不要反问用户。"
)


def brand_aliases(brand: Brand) -> List[str]:
    aliases = [brand.name] + [a.strip() for a in (brand.aliases or "").replace("，", ",").split(",") if a.strip()]
    seen, result = set(), []
    for a in aliases:
        if a and a not in seen:
            seen.add(a)
            result.append(a)
    return result


def competitor_names(brand: Brand) -> List[str]:
    return [c.strip() for c in re.split(r"[,，\n]", brand.competitors or "") if c.strip()]


def _alias_re(alias: str) -> re.Pattern:
    if re.fullmatch(r"[A-Za-z0-9 .\-()（）]+", alias):
        return re.compile(rf"(?<![A-Za-z0-9]){re.escape(alias)}(?![A-Za-z0-9])")
    return re.compile(re.escape(alias))


def extract_urls(answer: str) -> List[str]:
    return re.findall(r"https?://[^\s\)\]】<>\"'，。；]+", answer or "")


def domain_of(url: str) -> str:
    netloc = urlparse(url).netloc.lower()
    return netloc[4:] if netloc.startswith("www.") else netloc


def analyze_answer(answer: str, brand: Brand) -> dict:
    """对单条 AI 回答做品牌提及/排名/信源判定（纯规则，不用 LLM）。"""
    aliases = brand_aliases(brand)
    comps = competitor_names(brand)

    # 品牌命中（含否定语境检查）
    hits: List[tuple] = []
    for alias in aliases:
        for m in _alias_re(alias).finditer(answer):
            negated = bool(NEGATION_RE.search(answer[max(0, m.start() - 20): m.start()]))
            hits.append((m.start(), negated))
    hits.sort()
    brand_mentioned = any(not neg for _, neg in hits)
    first_hit = next((p for p, neg in hits if not neg), None)
    only_negated = bool(hits) and all(neg for _, neg in hits)

    # 负面线索：首次品牌提及 ±80/160 字符窗口
    negative_cues: List[str] = []
    if first_hit is not None:
        window = answer[max(0, first_hit - 80): first_hit + 160]
        negative_cues = [c for c in NEG_CUES if c in window]

    # 排名：品牌 + 竞品按首次出现位置
    entity_first = {}
    if first_hit is not None:
        entity_first["__brand__"] = first_hit
    for c in comps:
        m = _alias_re(c).search(answer)
        if m:
            entity_first[c] = m.start()
    rank = None
    if first_hit is not None:
        order = [k for k, _ in sorted(entity_first.items(), key=lambda kv: kv[1])]
        rank = order.index("__brand__") + 1

    # 信源
    domains = [domain_of(u) for u in extract_urls(answer)]
    own_domain = bool(brand.domain) and brand.domain.lower() in domains
    comp_present = [c for c in comps if _alias_re(c).search(answer)]

    return {
        "brand_mentioned": brand_mentioned,
        "brand_rank": rank,
        "competitors_mentioned": comp_present,
        "cited_domains": domains,
        "own_domain_cited": own_domain,
        "negative_cues": negative_cues,
        "needs_review": only_negated or bool(negative_cues),
    }


def ask_engine(engine: dict, question: str) -> str:
    """向单个引擎提问（temperature 0.7，与真实用户提问口径一致）。"""
    client = LLMClient([engine])
    return client.chat(SAMPLING_SYSTEM, question, temperature=0.7, max_tokens=2000)


def start_run(run_id: int, brand_id: int, pairs: List[tuple]) -> None:
    """后台线程执行采样：pairs = [(query_id, question, market, engine), ...]。"""

    def worker():
        db = SessionLocal()
        try:
            run = db.query(MonitorRun).get(run_id)
            brand = db.query(Brand).get(brand_id)
            for query_id, question, market, engine in pairs:
                try:
                    answer = ask_engine(engine, question)
                    r = analyze_answer(answer, brand) if brand else {}
                    sample = MonitorSample(
                        run_id=run_id, query_id=query_id, engine=engine.get("name", ""), market=market,
                        answer=answer,
                        brand_mentioned=r.get("brand_mentioned", False),
                        brand_rank=r.get("brand_rank"),
                        competitors_mentioned=json.dumps(r.get("competitors_mentioned", []), ensure_ascii=False),
                        cited_domains=json.dumps(r.get("cited_domains", []), ensure_ascii=False),
                        own_domain_cited=r.get("own_domain_cited", False),
                        negative_cues=json.dumps(r.get("negative_cues", []), ensure_ascii=False),
                        needs_review=r.get("needs_review", False),
                    )
                except Exception as e:  # noqa: BLE001 - 单条失败不阻断批次
                    sample = MonitorSample(
                        run_id=run_id, query_id=query_id, engine=engine.get("name", ""), market=market,
                        error=str(e)[:300],
                    )
                db.add(sample)
                if run:
                    run.done += 1
                db.commit()
            if run:
                run.status = "completed"
                run.finished_at = datetime.utcnow()
                db.commit()
        finally:
            db.close()

    threading.Thread(target=worker, daemon=True).start()
