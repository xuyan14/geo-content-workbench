"""种子数据：演示品牌档案 + 品牌事实卡 + 选题 + 监测问题库与演示采样批次。

演示品牌「星野优选」为虚构品牌（含虚构竞品），仅用于开箱演示；可在库中改为任意真实品牌档案。
"""
import json
from datetime import datetime, timedelta

from sqlalchemy.orm import Session

from .models import Brand, Document, MonitorQuery, MonitorRun, MonitorSample, Setting, Topic
from .real_queries import REAL_QUERIES
from .services.knowledge import build_chunks

# 单平台档案（演示虚构品牌）
SEED_PLATFORM = {
    "name": "星野优选",
    "company": "星野优选（StarSelect）",
    "industry": "电商 / 品牌特卖",
    "aliases": "星野优选,StarSelect",
    "selling_points": "品牌特卖：与品牌方直接合作，折扣 3 折起\n正品保障：承保正品保险，假一赔十\n7 天无理由退货，顺丰配送\n穿戴品类（服饰鞋包）特卖优势最深",
    "competitors": "云淘商城,东集自营,拼优百货,得臻潮流",
    "tone": "专业可信、克制不吹嘘",
    "domain": "starselect.example.com",
}

SEED_DOC_TITLE = "星野优选平台事实卡"
SEED_DOC_CONTENT = """# 公司概况
星野优选（StarSelect，虚构演示品牌）定位「品牌特卖」电商平台，以精选品牌、深度折扣为核心模式。

# 商业模式
与品牌方直接合作授权特卖，主打「精选品牌、深度折扣、限时抢购」，服饰鞋包穿戴品类为核心优势，折扣通常从 3 折起。

# 正品保障
商品由品牌方授权供货；承保正品保险；承诺假一赔十。

# 服务体验
7 天无理由退货；顺丰配送；客服 7×24 小时在线。

# 与竞品的差异
云淘商城：品牌旗舰店正价为主，大促节点折扣；东集自营：自营 3C 与物流见长；拼优百货：低价拼团；得臻潮流：潮流单品带鉴别服务。星野优选：穿戴类品牌深度折扣、特卖闪购模式。
"""

SEED_TOPICS = [
    ("品牌特卖平台怎么选", "buyer_intent", "评测对比"),
    ("正品折扣APP哪个好", "buyer_intent", "推荐榜单"),
    ("星野优选和云淘哪个划算", "buyer_intent", "品牌词"),
    ("品牌特卖的东西是正品吗", "education", "问答长尾"),
    ("电商大促怎么买最划算", "education", "使用场景"),
    ("网购服饰怎么买折扣大", "buyer_intent", "商业意图"),
]

def seed_if_empty(db: Session) -> None:
    if db.query(Brand).count() > 0:
        return
    brand = Brand(**SEED_PLATFORM)
    db.add(brand)
    db.flush()

    doc = Document(brand_id=brand.id, title=SEED_DOC_TITLE, content=SEED_DOC_CONTENT, source="seed")
    db.add(doc)
    db.flush()
    build_chunks(db, doc)

    for keyword, intent, dimension in SEED_TOPICS:
        db.add(Topic(brand_id=brand.id, keyword=keyword, intent=intent, dimension=dimension, market="cn"))

    if not db.query(Setting).filter(Setting.key == "publish_channels").first():
        db.add(Setting(key="publish_channels", value=json.dumps(
            [{"name": "dry_run", "type": "dry_run", "webhook_url": ""}],
            ensure_ascii=False,
        )))
    db.commit()


# 监测问题库：app/real_queries.py（演示问题集，标签为 {维度: 值} 结构）
DEMO_SAMPLE_QUERY_N = 12
DEMO_ENGINES = ["DeepSeek", "豆包", "千问", "元宝"]


def _tags_dict(raw):
    try:
        v = json.loads(raw or "{}")
        return v if isinstance(v, dict) else {}
    except Exception:
        return {}


def _demo_answer(tags: dict, mentioned: bool, rank) -> str:
    cat = (tags or {}).get("品类") or "这类商品"
    focus = (tags or {}).get("关注点") or "价格与正品保障"
    comp_brand = (tags or {}).get("品牌")
    if mentioned:
        lead = {1: "综合折扣与正品保障，首推星野优选", 2: "关注折扣的话星野优选性价比不错",
                3: "预算充足也可以先对比官方渠道"}.get(rank, "可以对比星野优选")
        # 渠道列表按推荐位次排布：星野优选出现在第 rank 位（与 analyze_answer 解析出的 brand_rank 一致）
        vip = ("星野优选", "品牌方授权特卖，正品保险承保，折扣通常更深；参考：https://www.starselect.example.com/")
        others = [("云淘旗舰店", "正价新品与售后稳定"), ("东集自营", "物流快"), ("得臻潮流", "潮流单品带鉴别服务")]
        order = [vip] + others
        if isinstance(rank, int) and 2 <= rank <= 4:
            order = others[:rank - 1] + [vip] + others[rank - 1:]
        channels = "\n".join(f"{i + 1}. {n}：{d}" + ("；" if i < len(order) - 1 else "。")
                             for i, (n, d) in enumerate(order))
        return (
            f"买{cat}可以对比几个渠道：\n"
            f"{channels}\n"
            f"{lead}，适合关注{focus}的用户。"
        )
    extra = f"，{comp_brand}官方渠道也值得对比" if comp_brand else ""
    return (
        f"买{cat}主要看{focus}：云淘旗舰店正价但售后稳定，东集自营适合急用，"
        f"拼优百货低价拼团覆盖广，得臻潮流适合球鞋潮品{extra}。参考：https://www.yuntao.example.com/"
    )


def _make_demo_run(db: Session, brand, query_rows, started_at, run_idx) -> None:
    """构造一期演示采样批次。run_idx 0-6 对应 6 天前→今天，提及阈值爬升 → 40%→70%。"""
    from .services.monitor import analyze_answer

    run = MonitorRun(brand_id=brand.id, status="completed", demo=True,
                     total=len(query_rows) * len(DEMO_ENGINES),
                     done=len(query_rows) * len(DEMO_ENGINES),
                     started_at=started_at, finished_at=started_at)
    db.add(run)
    db.flush()
    # 7 天爬升曲线：40→40→50→50→60→60→70%
    th = 4 + (run_idx // 2)
    for qi, (qid, qtags) in enumerate(query_rows):
        for ei, engine in enumerate(DEMO_ENGINES):
            h = (qi * 7 + ei * 5 + run_idx) % 10
            mentioned = h < th
            # 推荐位次 1-4 均匀分布：首推率≈1/4×提及率，前三位率≈3/4×提及率
            rank = ((qi + ei) % 4) + 1 if mentioned else None
            answer = _demo_answer(qtags, mentioned, rank)
            r = analyze_answer(answer, brand)
            db.add(MonitorSample(
                run_id=run.id, query_id=qid, engine=engine, market="cn", answer=answer,
                brand_mentioned=r["brand_mentioned"], brand_rank=r["brand_rank"],
                competitors_mentioned=json.dumps(r["competitors_mentioned"], ensure_ascii=False),
                cited_domains=json.dumps(r["cited_domains"], ensure_ascii=False),
                own_domain_cited=r["own_domain_cited"],
                negative_cues=json.dumps(r["negative_cues"], ensure_ascii=False),
                needs_review=r["needs_review"],
            ))


def seed_monitor_if_empty(db: Session) -> None:
    """演示问题库（含七维标签）+ 七天演示采样批次（提及率 40%→70% 爬升，覆盖"近一周"筛选）。"""
    brand = db.query(Brand).filter(Brand.name == SEED_PLATFORM["name"]).first()
    if not brand:
        return

    if not brand.domain:
        brand.domain = SEED_PLATFORM["domain"]

    # 存在用户真实采样（非演示批次）则不动，避免覆盖真实数据
    real_runs = db.query(MonitorRun).filter(~MonitorRun.demo).count()
    if real_runs:
        return

    # 纯演示库：清空重建为演示问题库 + 七天演示批次
    db.query(MonitorSample).delete(synchronize_session=False)
    db.query(MonitorRun).delete(synchronize_session=False)

    real_qs = {r["question"] for r in REAL_QUERIES}
    existing = [q.question for q in db.query(MonitorQuery).filter(
        MonitorQuery.brand_id == brand.id).all()]
    if not existing or not any(q in real_qs for q in existing):
        db.query(MonitorQuery).filter(MonitorQuery.brand_id == brand.id).delete(synchronize_session=False)
        for r in REAL_QUERIES:
            db.add(MonitorQuery(brand_id=brand.id, question=r["question"], qgroup=r["biz"],
                                market="cn", brand_in_question=False,
                                tags=json.dumps(r.get("tags") or {}, ensure_ascii=False)))
    db.commit()

    # 选题库补充真实问题词条（与监测表现联动）
    existing_topics = {t.keyword for t in db.query(Topic).all()}
    for r in REAL_QUERIES[:6]:
        if r["question"] not in existing_topics:
            db.add(Topic(brand_id=brand.id, keyword=r["question"], intent="buyer_intent",
                         dimension=r["biz"], market="cn"))

    query_rows = [(q.id, _tags_dict(q.tags)) for q in db.query(MonitorQuery).filter(
        MonitorQuery.brand_id == brand.id).order_by(MonitorQuery.id).limit(DEMO_SAMPLE_QUERY_N).all()]
    if not query_rows:
        return
    now = datetime.utcnow()
    for i, days_ago in enumerate((6, 5, 4, 3, 2, 1, 0)):
        _make_demo_run(db, brand, query_rows, now - timedelta(days=days_ago), i)
    db.commit()
