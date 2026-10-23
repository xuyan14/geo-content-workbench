"""REST API 路由。"""
import html as html_mod
import json
import re
from datetime import datetime
from pathlib import Path
from typing import List, Optional

import httpx
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy.orm import Session

from .ai.client import LLMClient, _env_providers
from .database import get_db
from .models import Article, Brand, CardReview, Chunk, Document, MonitorQuery, MonitorRun, MonitorSample, Setting, Topic
from .services import generator, knowledge, publisher, reviewer, topics as topic_svc
from .services import monitor as monitor_svc

router = APIRouter(prefix="/api")

# Answerbit OpenAPI 适配路由（/api/answerbit/*）
from .api_answerbit import router as answerbit_router  # noqa: E402
router.include_router(answerbit_router)

STATUS_LABELS = {
    "draft": "草稿",
    "pending_review": "待审核",
    "approved": "已通过",
    "published": "已发布",
    "rejected": "已驳回",
}


# ---------- helpers ----------

def _get_llm(db: Session) -> LLMClient:
    row = db.query(Setting).filter(Setting.key == "llm_providers").first()
    providers = []
    if row and row.value:
        try:
            providers = json.loads(row.value)
        except json.JSONDecodeError:
            providers = []
    providers = providers + _env_providers()
    return LLMClient(providers)


def _brand_or_404(db: Session, brand_id: int) -> Brand:
    brand = db.query(Brand).get(brand_id)
    if not brand:
        raise HTTPException(404, "品牌不存在")
    return brand


def _article_or_404(db: Session, article_id: int) -> Article:
    article = db.query(Article).get(article_id)
    if not article:
        raise HTTPException(404, "内容不存在")
    return article


def article_dict(a: Article, with_body: bool = True) -> dict:
    data = {
        "id": a.id,
        "brand_id": a.brand_id,
        "topic_id": a.topic_id,
        "title": a.title,
        "template": a.template,
        "status": a.status,
        "status_label": STATUS_LABELS.get(a.status, a.status),
        "evidence": a.evidence,
        "rule_issues": json.loads(a.rule_issues or "[]"),
        "ai_review": json.loads(a.ai_review or "{}"),
        "score": a.score,
        "source": a.source or "ai",
        "gen_meta": _doc_meta(a.gen_meta) or {},
        "publish_channel": a.publish_channel,
        "published_url": a.published_url,
        "created_at": a.created_at.isoformat() if a.created_at else "",
        "updated_at": a.updated_at.isoformat() if a.updated_at else "",
    }
    if with_body:
        data["body"] = a.body
    return data


# ---------- schemas ----------

class DocIn(BaseModel):
    brand_id: int
    title: str
    content: str
    source: str = "paste"


class ImportCardsIn(BaseModel):
    brand_id: int
    limit: int = 0  # 0 = 全量导入


def _doc_meta(raw):
    """文档元数据：知识卡导入时写入 {card_id, topics, quality, status, source_types}。"""
    if not raw:
        return None
    try:
        v = json.loads(raw)
        return v if isinstance(v, dict) else None
    except Exception:
        return None


CARDS_FILE = Path(__file__).resolve().parent / "data" / "knowledge_cards.jsonl"

_cards_cache: Optional[list] = None


def _load_cards() -> list:
    """全量知识卡（模块级缓存：文件不热更，重启进程生效）。"""
    global _cards_cache
    if _cards_cache is None:
        cards = []
        if CARDS_FILE.exists():
            with open(CARDS_FILE, encoding="utf-8") as f:
                for line in f:
                    if line.strip():
                        cards.append(json.loads(line))
        _cards_cache = cards
    return _cards_cache


def _card_summary(card: dict, review=None) -> dict:
    """卡片摘要（列表用）：不含 content 全文与 sources 明细，控制单页体积。"""
    srcs = card.get("sources") or []
    content = card.get("content") or ""
    return {
        "card_id": card.get("card_id", ""),
        "title": card.get("title", ""),
        "topics": card.get("topics") or [],
        "categories": card.get("categories") or [],
        "quality": card.get("quality", ""),
        "status": card.get("status", ""),
        "source_types": card.get("source_types") or [],
        "pubs": sorted({s.get("publisher", "") for s in srcs if s.get("publisher")}),
        "time": card.get("time", ""),
        "doc_time": card.get("doc_time", ""),
        "cautions_count": len(card.get("cautions") or []),
        "conflicts_count": len(card.get("conflicts") or []),
        "merged_count": len(card.get("merged_from") or []),
        "source_count": len(srcs),
        "content_head": content[:160],
        "content_len": len(content),
        # 前端本地搜索用：标题 + 正文 + 使用提醒 + 原文引文
        "search_text": " ".join(
            [card.get("title", ""), content]
            + [x for x in (card.get("cautions") or [])]
            + [s.get("quote", "") for s in srcs if s.get("quote")]
        ),
        "review": {"tag": review.tag, "note": review.note} if review else None,
    }


@router.get("/knowledge-cards")
def list_knowledge_cards(db: Session = Depends(get_db)):
    """知识卡列表（含人工审核标记）：还原 GEO 知识治理中心的卡片视图。"""
    reviews = {r.card_id: r for r in db.query(CardReview).all()}
    return [_card_summary(c, reviews.get(c.get("card_id"))) for c in _load_cards()]


@router.get("/knowledge-cards/{card_id}")
def get_knowledge_card(card_id: str, db: Session = Depends(get_db)):
    """知识卡详情：正文全文 + 使用提醒 + 待确认差异 + 来源引用。"""
    for c in _load_cards():
        if c.get("card_id") == card_id:
            r = db.query(CardReview).get(card_id)
            return {**c, "review": ({"tag": r.tag, "note": r.note} if r else None)}
    raise HTTPException(404, "知识卡不存在")


class CardReviewIn(BaseModel):
    tag: str  # passed/rejected/deleted，传空表示取消标记
    note: str = ""


@router.post("/knowledge-cards/{card_id}/review")
def review_knowledge_card(card_id: str, payload: CardReviewIn, db: Session = Depends(get_db)):
    """人工审核：通过 / 拒绝 / 删除 + 备注（持久化到 card_reviews）。"""
    if not any(c.get("card_id") == card_id for c in _load_cards()):
        raise HTTPException(404, "知识卡不存在")
    if payload.tag and payload.tag not in ("passed", "rejected", "deleted"):
        raise HTTPException(400, "tag 仅支持 passed/rejected/deleted")
    row = db.query(CardReview).get(card_id)
    if not payload.tag:
        if row:
            db.delete(row)
            db.commit()
        return {"card_id": card_id, "tag": "", "note": ""}
    if not row:
        row = CardReview(card_id=card_id)
        db.add(row)
    row.tag = payload.tag
    row.note = payload.note or ""
    db.commit()
    return {"card_id": card_id, "tag": row.tag, "note": row.note}


def _card_content(card: dict) -> str:
    """知识卡 → 文档正文：正文 + 注意事项 + 来源引用（供 RAG 分块与证据注入）。"""
    parts = [card.get("content") or ""]
    cautions = card.get("cautions") or []
    if cautions:
        parts.append("\n注意事项：\n" + "\n".join(f"- {c}" for c in cautions))
    srcs = card.get("sources") or []
    if srcs:
        lines = []
        for s in srcs[:3]:
            q = (s.get("quote") or "").strip()
            lines.append(f"- 《{s.get('doc_title', '')}》（{s.get('publisher', '')} · {s.get('source_type', '')}）：{q[:200]}")
        parts.append("\n来源引用：\n" + "\n".join(lines))
    return "\n".join(parts)


@router.post("/documents/import-cards")
def import_knowledge_cards(payload: ImportCardsIn, db: Session = Depends(get_db)):
    """导入 GEO 知识治理中心的知识卡数据包（app/data/knowledge_cards.jsonl，972 张）。

    每张卡 = 一篇知识库文档（标题 + 正文/注意事项/来源引用），自动分块进入 RAG 证据池；
    按 card_id 幂等，重复导入自动跳过。
    """
    _brand_or_404(db, payload.brand_id)
    if not CARDS_FILE.exists():
        raise HTTPException(404, "知识卡数据包不存在（app/data/knowledge_cards.jsonl）")
    existing = set()
    for d in db.query(Document).filter(Document.source == "knowledge_card").all():
        m = _doc_meta(d.meta)
        if m and m.get("card_id"):
            existing.add(m["card_id"])
    imported, skipped = 0, 0
    from .services.knowledge import build_chunks
    with open(CARDS_FILE, encoding="utf-8") as f:
        for i, line in enumerate(f):
            if not line.strip():
                continue
            card = json.loads(line)
            cid = card.get("card_id")
            if cid in existing:
                skipped += 1
                continue
            if payload.limit and imported >= payload.limit:
                skipped += 1
                continue
            doc = Document(
                brand_id=payload.brand_id, title=(card.get("title") or "未命名知识卡")[:200],
                source="knowledge_card", content=_card_content(card),
                meta=json.dumps({
                    "card_id": cid,
                    "topics": card.get("topics") or [],
                    "quality": card.get("quality") or "",
                    "status": card.get("status") or "",
                    "source_types": card.get("source_types") or [],
                }, ensure_ascii=False),
            )
            db.add(doc)
            db.flush()
            build_chunks(db, doc)
            imported += 1
            if imported % 100 == 0:
                db.commit()
    db.commit()
    return {"imported": imported, "skipped": skipped}


class TopicIn(BaseModel):
    brand_id: int
    keyword: str
    intent: str = "education"
    dimension: str = "问答长尾"
    market: str = "cn"


class ExpandIn(BaseModel):
    brand_id: int
    seed_keywords: str = ""
    count: int = 8


class GenerateIn(BaseModel):
    brand_id: int
    topic_id: int
    template: str = "对比选购"
    # 目标模型（多引擎生成元数据，存 gen_meta）
    models: List[str] = []
    # 范文仿写：三选一（ref_doc_id 知识库文档 / ref_title+ref_body 手动内容 / ref_url 链接）
    ref_doc_id: Optional[int] = None
    ref_title: str = ""
    ref_body: str = ""
    ref_url: str = ""


class RefUrlIn(BaseModel):
    url: str


class ManualIn(BaseModel):
    brand_id: int
    title: str
    body: str
    template: str = ""


class ArticleUpdate(BaseModel):
    title: Optional[str] = None
    body: Optional[str] = None


class PublishIn(BaseModel):
    channel: str = "dry_run"


class ProviderIn(BaseModel):
    name: str = ""
    base_url: str = ""
    model: str = ""
    api_key: str = ""
    market: str = "both"  # both/cn/global：采样时的市场路由


class LLMSettingsIn(BaseModel):
    providers: List[ProviderIn]


# ---------- stats ----------

@router.get("/stats")
def stats(db: Session = Depends(get_db)):
    articles = db.query(Article).all()
    by_status = {s: 0 for s in STATUS_LABELS}
    for a in articles:
        by_status[a.status] = by_status.get(a.status, 0) + 1
    return {
        "brands": db.query(Brand).count(),
        "documents": db.query(Document).count(),
        "chunks": db.query(Chunk).count(),
        "topics": db.query(Topic).count(),
        "topics_pending": db.query(Topic).filter(Topic.status == "pending").count(),
        "monitor_queries": db.query(MonitorQuery).filter(MonitorQuery.active == True).count(),  # noqa: E712
        "articles": len(articles),
        "articles_by_status": by_status,
        "recent": [article_dict(a, with_body=False) for a in articles[-5:][::-1]],
        "templates": list(generator.TEMPLATES.keys()),
    }


# ---------- platform（单平台档案）----------

def _get_platform(db: Session) -> Brand:
    """单平台模式：全局唯一档案，不存在则自动初始化。"""
    brand = db.query(Brand).order_by(Brand.id).first()
    if not brand:
        from .seed import SEED_PLATFORM
        db.add(Brand(**SEED_PLATFORM))
        db.commit()
        brand = db.query(Brand).order_by(Brand.id).first()
    return brand


@router.get("/platform")
def get_platform(db: Session = Depends(get_db)):
    brand = _get_platform(db)
    return {
        "id": brand.id, "name": brand.name, "company": brand.company, "industry": brand.industry,
        "aliases": brand.aliases, "selling_points": brand.selling_points, "competitors": brand.competitors,
        "tone": brand.tone, "domain": brand.domain,
        "doc_count": db.query(Document).filter(Document.brand_id == brand.id).count(),
        "topic_count": db.query(Topic).filter(Topic.brand_id == brand.id).count(),
        "article_count": db.query(Article).filter(Article.brand_id == brand.id).count(),
    }


# ---------- knowledge base ----------

@router.get("/documents")
def list_documents(brand_id: int, db: Session = Depends(get_db)):
    docs = db.query(Document).filter(Document.brand_id == brand_id).order_by(Document.id.desc()).all()
    return [
        {"id": d.id, "title": d.title, "source": d.source, "chunk_count": d.chunk_count,
         "content_len": len(d.content), "created_at": d.created_at.isoformat(),
         "meta": _doc_meta(d.meta)}
        for d in docs
    ]


@router.post("/documents")
def create_document(payload: DocIn, db: Session = Depends(get_db)):
    _brand_or_404(db, payload.brand_id)
    if not payload.content.strip():
        raise HTTPException(400, "内容不能为空")
    doc = Document(brand_id=payload.brand_id, title=payload.title, content=payload.content, source=payload.source)
    db.add(doc)
    db.flush()
    n = knowledge.build_chunks(db, doc)
    return {"id": doc.id, "chunk_count": n}


class DocUrlIn(BaseModel):
    brand_id: int
    url: str
    title: str = ""


def _extract_article(html: str) -> tuple:
    """极简正文提取：去脚本样式导航 → 块级标签断行 → 剥离标签 → 压缩空白。"""
    m = re.search(r"<title[^>]*>(.*?)</title>", html, re.S | re.I)
    title = re.sub(r"\s+", " ", m.group(1)).strip() if m else ""
    body = re.sub(r"<(script|style|noscript|nav|header|footer|aside|iframe)[^>]*>.*?</\1>", " ", html, flags=re.S | re.I)
    body = re.sub(r"<!--.*?-->", " ", body, flags=re.S)
    body = re.sub(r"</(p|div|br|li|h[1-6]|tr|section|article|blockquote)>", "\n", body, flags=re.I)
    body = re.sub(r"<br\s*/?>", "\n", body, flags=re.I)
    text = re.sub(r"<[^>]+>", " ", body)
    text = html_mod.unescape(text)
    lines = [re.sub(r"[ \t]+", " ", ln).strip() for ln in text.split("\n")]
    return title, "\n".join(ln for ln in lines if len(ln) >= 10)


@router.post("/documents/url")
def create_document_from_url(payload: DocUrlIn, db: Session = Depends(get_db)):
    """输入网页 URL 自动抓取并解析正文，入库为知识文档。"""
    _brand_or_404(db, payload.brand_id)
    url = payload.url.strip()
    if not re.match(r"^https?://", url):
        raise HTTPException(400, "请输入 http/https 开头的链接")
    try:
        resp = httpx.get(url, timeout=15, follow_redirects=True,
                         headers={"User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36"})
        resp.raise_for_status()
    except Exception as e:
        raise HTTPException(400, f"网页抓取失败：{str(e)[:120]}")
    page_title, content = _extract_article(resp.text)
    if len(content) < 50:
        raise HTTPException(400, "网页正文提取内容过少（可能是纯脚本渲染页），请改用粘贴文章方式")
    title = payload.title.strip() or page_title or url[:80]
    doc = Document(brand_id=payload.brand_id, title=title, content=content,
                   source="url", meta=json.dumps({"url": url}, ensure_ascii=False))
    db.add(doc)
    db.flush()
    n = knowledge.build_chunks(db, doc)
    return {"id": doc.id, "chunk_count": n, "title": title, "content_len": len(content)}


@router.delete("/documents/{doc_id}")
def delete_document(doc_id: int, db: Session = Depends(get_db)):
    doc = db.query(Document).get(doc_id)
    if not doc:
        raise HTTPException(404, "文档不存在")
    db.query(Chunk).filter(Chunk.document_id == doc_id).delete()
    db.delete(doc)
    db.commit()
    return {"ok": True}


@router.post("/documents/{doc_id}/reprocess")
def reprocess_document(doc_id: int, db: Session = Depends(get_db)):
    doc = db.query(Document).get(doc_id)
    if not doc:
        raise HTTPException(404, "文档不存在")
    n = knowledge.build_chunks(db, doc)
    return {"chunk_count": n}


@router.get("/documents/{doc_id}/chunks")
def list_chunks(doc_id: int, db: Session = Depends(get_db)):
    chunks = db.query(Chunk).filter(Chunk.document_id == doc_id).order_by(Chunk.seq).all()
    return [{"id": c.id, "seq": c.seq, "keywords": c.keywords, "text": c.text[:300]} for c in chunks]


# ---------- topics ----------

@router.get("/topics")
def list_topics(brand_id: int, status: Optional[str] = None, db: Session = Depends(get_db)):
    # Answerbit 模式下 topics 维持本地内容选题（推荐选题与本地 Topic 语义不合，避免布局异常）
    q = db.query(Topic).filter(Topic.brand_id == brand_id)
    if status:
        q = q.filter(Topic.status == status)
    return [
        {"id": t.id, "keyword": t.keyword, "intent": t.intent, "dimension": t.dimension,
         "market": t.market, "status": t.status, "created_at": t.created_at.isoformat()}
        for t in q.order_by(Topic.id.desc()).all()
    ]


@router.post("/topics")
def create_topic(payload: TopicIn, db: Session = Depends(get_db)):
    _brand_or_404(db, payload.brand_id)
    topic = Topic(**payload.model_dump())
    db.add(topic)
    db.commit()
    return {"id": topic.id}


@router.delete("/topics/{topic_id}")
def delete_topic(topic_id: int, db: Session = Depends(get_db)):
    topic = db.query(Topic).get(topic_id)
    if topic:
        db.delete(topic)
        db.commit()
    return {"ok": True}


@router.post("/topics/expand")
def expand_topics(payload: ExpandIn, db: Session = Depends(get_db)):
    brand = _brand_or_404(db, payload.brand_id)
    client = _get_llm(db)
    items = topic_svc.expand(client, brand, payload.seed_keywords, payload.count)
    created = []
    for it in items:
        topic = Topic(brand_id=brand.id, keyword=it["keyword"], intent=it.get("intent", "education"),
                      dimension=it.get("dimension", "问答长尾"), market=it.get("market", "cn"))
        db.add(topic)
        db.flush()
        created.append({"id": topic.id, **it})
    db.commit()
    return {"created": created, "degraded": not client.available}


# ---------- articles ----------

@router.get("/articles")
def list_articles(status: Optional[str] = None, brand_id: Optional[int] = None, db: Session = Depends(get_db)):
    q = db.query(Article)
    if status:
        q = q.filter(Article.status == status)
    if brand_id:
        q = q.filter(Article.brand_id == brand_id)
    return [article_dict(a, with_body=False) for a in q.order_by(Article.id.desc()).all()]


@router.get("/articles/{article_id}")
def get_article(article_id: int, db: Session = Depends(get_db)):
    return article_dict(_article_or_404(db, article_id))


@router.patch("/articles/{article_id}")
def update_article(article_id: int, payload: ArticleUpdate, db: Session = Depends(get_db)):
    article = _article_or_404(db, article_id)
    if payload.title is not None:
        article.title = payload.title
    if payload.body is not None:
        article.body = payload.body
    article.updated_at = datetime.utcnow()
    db.commit()
    return article_dict(article)


@router.delete("/articles/{article_id}")
def delete_article(article_id: int, db: Session = Depends(get_db)):
    article = _article_or_404(db, article_id)
    db.delete(article)
    db.commit()
    return {"ok": True}


def _resolve_reference(payload, db: Session, brand: Brand) -> Optional[dict]:
    """范文仿写：解析仿写对象（知识库文档 / 手动内容 / 链接抓取），返回 {title, body, ref_url} 或 None。"""
    if payload.ref_doc_id:
        doc = db.query(Document).get(payload.ref_doc_id)
        if not doc or doc.brand_id != brand.id:
            raise HTTPException(404, "参考范文文档不存在")
        return {"title": doc.title, "body": doc.content, "ref_url": ""}
    if payload.ref_body.strip():
        return {"title": payload.ref_title.strip() or "（手动指定范文）",
                "body": payload.ref_body, "ref_url": ""}
    if payload.ref_url.strip():
        title, text = _fetch_article_text(payload.ref_url.strip())
        return {"title": title or payload.ref_title.strip() or "（链接范文）", "body": text,
                "ref_url": payload.ref_url.strip()}
    return None


def _fetch_article_text(url: str) -> tuple:
    """抓取网页并提取正文（复用 URL 导入的清洗逻辑），不落库。"""
    if not url.startswith(("http://", "https://")):
        raise HTTPException(400, "请输入以 http(s):// 开头的链接")
    try:
        r = httpx.get(url, timeout=15, follow_redirects=True,
                      headers={"User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
                                             "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126 Safari/537.36"})
        r.raise_for_status()
    except httpx.HTTPError as e:
        raise HTTPException(400, f"链接抓取失败：{e.__class__.__name__}")
    ctype = r.headers.get("content-type", "")
    if "html" not in ctype and "text" not in ctype:
        raise HTTPException(400, "链接内容不是网页或文本")
    title, text = _extract_article(r.text)
    if len(text) < 50:
        raise HTTPException(400, "该网页未能解析出有效正文（正文不足 50 字），请改用手动指定内容")
    return title, text


@router.post("/articles/reference/parse")
def parse_reference(payload: RefUrlIn):
    """解析范文链接：返回 {title, text} 供前端预览确认，不落库。"""
    title, text = _fetch_article_text(payload.url.strip())
    return {"title": title or "（未命名范文）", "text": text}


@router.get("/documents/{doc_id}")
def get_document(doc_id: int, db: Session = Depends(get_db)):
    doc = db.query(Document).get(doc_id)
    if not doc:
        raise HTTPException(404, "文档不存在")
    return {"id": doc.id, "title": doc.title, "source": doc.source, "content": doc.content,
            "created_at": doc.created_at.isoformat()}


@router.post("/articles/generate")
def generate_article(payload: GenerateIn, db: Session = Depends(get_db)):
    brand = _brand_or_404(db, payload.brand_id)
    topic = db.query(Topic).get(payload.topic_id)
    if not topic or topic.brand_id != brand.id:
        raise HTTPException(404, "选题不存在")

    reference = _resolve_reference(payload, db, brand)
    template = generator.IMITATE_TEMPLATE if reference else payload.template

    chunks = knowledge.retrieve(db, brand, topic.keyword)
    client = _get_llm(db)
    result = generator.generate(client, brand, topic, template, chunks, reference=reference)

    evidence_text = "\n\n".join(f"[证据{i}] {c.text[:400]}" for i, c in enumerate(chunks, 1))
    rule_issues = reviewer.rule_check(result["body"], evidence_text)
    ai = reviewer.ai_review(client, result["body"], evidence_text)

    article = Article(
        brand_id=brand.id,
        topic_id=topic.id,
        title=result["title"],
        template=template,
        body=result["body"],
        status="pending_review",
        evidence=evidence_text,
        rule_issues=json.dumps(rule_issues, ensure_ascii=False),
        ai_review=json.dumps(ai, ensure_ascii=False),
        score=ai.get("score"),
        source="ai",
        gen_meta=json.dumps({
            "models": payload.models, "question": topic.keyword,
            "ref_title": (reference or {}).get("title", ""),
            "ref_url": (reference or {}).get("ref_url", ""),
        }, ensure_ascii=False),
    )
    db.add(article)
    topic.status = "used"
    db.commit()
    return article_dict(article)


@router.post("/articles/manual")
def create_manual_article(payload: ManualIn, db: Session = Depends(get_db)):
    """本地上传文章：直接入库，进入待审核状态。"""
    brand = _brand_or_404(db, payload.brand_id)
    title = payload.title.strip()
    body = payload.body.strip()
    if len(title) < 2:
        raise HTTPException(400, "标题至少 2 个字符")
    if len(body) < 50:
        raise HTTPException(400, "正文至少 50 个字符")

    article = Article(
        brand_id=brand.id,
        topic_id=None,
        title=title,
        template=payload.template or "本地上传",
        body=body,
        status="pending_review",
        rule_issues="[]",
        ai_review="{}",
        source="upload",
    )
    db.add(article)
    db.commit()
    return article_dict(article)


@router.post("/articles/{article_id}/review")
def review_article(article_id: int, db: Session = Depends(get_db)):
    article = _article_or_404(db, article_id)
    client = _get_llm(db)
    rule_issues = reviewer.rule_check(article.body, article.evidence)
    ai = reviewer.ai_review(client, article.body, article.evidence)
    article.rule_issues = json.dumps(rule_issues, ensure_ascii=False)
    article.ai_review = json.dumps(ai, ensure_ascii=False)
    article.score = ai.get("score")
    if article.status in ("draft", "rejected"):
        article.status = "pending_review"
    db.commit()
    return article_dict(article)


@router.post("/articles/{article_id}/approve")
def approve_article(article_id: int, db: Session = Depends(get_db)):
    article = _article_or_404(db, article_id)
    article.status = "approved"
    db.commit()
    return article_dict(article)


@router.post("/articles/{article_id}/reject")
def reject_article(article_id: int, db: Session = Depends(get_db)):
    article = _article_or_404(db, article_id)
    article.status = "rejected"
    db.commit()
    return article_dict(article)


@router.post("/articles/{article_id}/publish")
def publish_article(article_id: int, payload: PublishIn, db: Session = Depends(get_db)):
    article = _article_or_404(db, article_id)
    if article.status != "approved":
        raise HTTPException(400, "仅已通过审核的内容可发布")
    row = db.query(Setting).filter(Setting.key == "publish_channels").first()
    channels = json.loads(row.value) if row and row.value else []
    try:
        result = publisher.publish_article(article.title, article.body, payload.channel, channels)
    except RuntimeError as e:
        raise HTTPException(502, str(e))
    article.status = "published"
    article.publish_channel = payload.channel
    article.published_url = result["url"]
    db.commit()
    return {"article": article_dict(article), "detail": result["detail"]}


# ---------- settings ----------

@router.get("/settings/llm")
def get_llm_settings(db: Session = Depends(get_db)):
    row = db.query(Setting).filter(Setting.key == "llm_providers").first()
    providers = json.loads(row.value) if row and row.value else []
    return {
        "providers": [{**p, "api_key": p.get("api_key", "")[:6] + "***" if p.get("api_key") else ""} for p in providers],
        "env_providers": [p["name"] for p in _env_providers()],
    }


@router.put("/settings/llm")
def save_llm_settings(payload: LLMSettingsIn, db: Session = Depends(get_db)):
    # 保留已存的完整 key（前端传回掩码时不清掉原值）
    row = db.query(Setting).filter(Setting.key == "llm_providers").first()
    old = json.loads(row.value) if row and row.value else []
    providers = []
    for p in payload.providers:
        data = p.model_dump()
        if data.get("api_key", "").endswith("***"):
            matched = next((o for o in old if o.get("name") == data["name"]), None)
            if matched:
                data["api_key"] = matched.get("api_key", "")
        if data.get("api_key"):
            providers.append(data)
    value = json.dumps(providers, ensure_ascii=False)
    if row:
        row.value = value
    else:
        db.add(Setting(key="llm_providers", value=value))
    db.commit()
    return {"saved": len(providers)}


@router.post("/settings/llm/test")
def test_llm(db: Session = Depends(get_db)):
    client = _get_llm(db)
    if not client.available:
        return {"results": [], "message": "未配置任何供应商（可在设置页添加，或设置环境变量）"}
    return {"results": client.ping()}


@router.get("/settings/channels")
def get_channels(db: Session = Depends(get_db)):
    row = db.query(Setting).filter(Setting.key == "publish_channels").first()
    channels = json.loads(row.value) if row and row.value else []
    if not any(c.get("name") == "dry_run" for c in channels):
        channels.insert(0, {"name": "dry_run", "type": "dry_run", "webhook_url": ""})
    return channels


@router.put("/settings/channels")
def save_channels(channels: List[dict], db: Session = Depends(get_db)):
    value = json.dumps(channels, ensure_ascii=False)
    row = db.query(Setting).filter(Setting.key == "publish_channels").first()
    if row:
        row.value = value
    else:
        db.add(Setting(key="publish_channels", value=value))
    db.commit()
    return {"saved": len(channels)}


# ---------- monitoring（监测中心）----------

class MQueryIn(BaseModel):
    brand_id: int
    question: str
    qgroup: str = "场景"
    market: str = "cn"
    brand_in_question: bool = False
    tags: dict = {}


def _parse_tags(raw):
    """标签兼容两种存储：{维度: 值} JSON 对象（GEO-词包口径）或旧逗号分隔列表。"""
    if not raw:
        return {}
    try:
        v = json.loads(raw)
        if isinstance(v, dict):
            return {str(k): str(x).strip() for k, x in v.items() if str(x).strip()}
    except Exception:
        pass
    return [t for t in raw.split(",") if t]


@router.get("/monitor/queries")
def list_mqueries(brand_id: int, db: Session = Depends(get_db)):
    # Answerbit 兼容数据源：已配置 API Key 时优先返回平台监控提问（同形状），失败回退本地
    from .api_answerbit import ab_enabled, ab_queries
    if ab_enabled(db):
        rows = ab_queries(db)
        if rows is not None:
            return rows
    qs = db.query(MonitorQuery).filter(MonitorQuery.brand_id == brand_id).order_by(MonitorQuery.id).all()
    return [
        {"id": q.id, "question": q.question, "qgroup": q.qgroup, "market": q.market,
         "brand_in_question": q.brand_in_question, "active": q.active,
         "tags": _parse_tags(q.tags)}
        for q in qs
    ]


@router.post("/monitor/queries")
def create_mquery(payload: MQueryIn, db: Session = Depends(get_db)):
    _brand_or_404(db, payload.brand_id)
    if not payload.question.strip():
        raise HTTPException(400, "问题不能为空")
    data = payload.model_dump()
    tg = data.get("tags") or {}
    data["tags"] = json.dumps({str(k): str(v).strip() for k, v in tg.items() if str(v).strip()},
                              ensure_ascii=False)
    q = MonitorQuery(**data)
    db.add(q)
    db.commit()
    return {"id": q.id}


@router.patch("/monitor/queries/{q_id}")
def toggle_mquery(q_id: int, db: Session = Depends(get_db)):
    # Answerbit 兼容：映射平台 prompt_update（status 1↔2），失败回退本地
    from .api_answerbit import ab_enabled, ab_query_toggle
    if ab_enabled(db):
        r = ab_query_toggle(db, q_id)
        if r is not None:
            return r
    q = db.query(MonitorQuery).get(q_id)
    if not q:
        raise HTTPException(404, "监测问题不存在")
    q.active = not q.active
    db.commit()
    return {"active": q.active}


@router.delete("/monitor/queries/{q_id}")
def delete_mquery(q_id: int, db: Session = Depends(get_db)):
    # Answerbit 兼容：映射平台 prompt_delete，失败回退本地
    from .api_answerbit import ab_enabled, ab_query_delete
    if ab_enabled(db):
        r = ab_query_delete(db, q_id)
        if r is not None:
            return r
    q = db.query(MonitorQuery).get(q_id)
    if q:
        db.delete(q)
        db.commit()
    return {"ok": True}


@router.get("/monitor/engines")
def monitor_engines(db: Session = Depends(get_db)):
    """可用采样引擎 = 已配置的 LLM 供应商（含环境变量注入）。"""
    return [
        {"name": p["name"], "model": p["model"], "market": p.get("market", "both")}
        for p in _get_llm(db).providers
    ]


class RunIn(BaseModel):
    brand_id: int
    engine_names: List[str] = []
    # 仅采样这些问题（选题库按筛选范围发起）；不传 = 全部启用监测的问题
    query_ids: Optional[List[int]] = None
    # 每个问题在每个引擎上的采样次数
    times: int = 1


@router.post("/monitor/runs")
def create_mrun(payload: RunIn, db: Session = Depends(get_db)):
    brand = _brand_or_404(db, payload.brand_id)
    q = db.query(MonitorQuery).filter(
        MonitorQuery.brand_id == brand.id, MonitorQuery.active == True  # noqa: E712
    )
    if payload.query_ids:
        q = q.filter(MonitorQuery.id.in_(payload.query_ids))
    queries = q.order_by(MonitorQuery.id).all()
    if not queries:
        raise HTTPException(400, "问题库为空：请先在选题库添加问题")
    if not 1 <= payload.times <= 5:
        raise HTTPException(400, "采样次数需在 1-5 之间")
    engines = _get_llm(db).providers
    if payload.engine_names:
        engines = [e for e in engines if e["name"] in payload.engine_names]
    if not engines:
        raise HTTPException(400, "未配置采样引擎：请在「设置」页添加 AI 供应商（或设置环境变量）")
    # 市场路由：中文题不打仅海外引擎，英文题不打仅国内引擎
    pairs = [
        (q2, e) for q2 in queries for e in engines
        if not (q2.market in ("cn", "global") and e.get("market", "both") not in ("both", q2.market))
    ] * payload.times
    if not pairs:
        raise HTTPException(400, "所选引擎与问题市场不匹配")
    run = MonitorRun(brand_id=brand.id, status="running", total=len(pairs), done=0)
    db.add(run)
    db.commit()
    monitor_svc.start_run(run.id, brand.id, [(q2.id, q2.question, q2.market, e) for q2, e in pairs])
    return {"id": run.id, "total": run.total, "queries": len(queries), "times": payload.times}


def _run_dict(r: MonitorRun) -> dict:
    return {
        "id": r.id, "brand_id": r.brand_id, "status": r.status, "total": r.total, "done": r.done,
        "started_at": r.started_at.isoformat() if r.started_at else "",
        "finished_at": r.finished_at.isoformat() if r.finished_at else "",
    }


@router.get("/monitor/runs")
def list_mruns(brand_id: int, db: Session = Depends(get_db)):
    # Answerbit 兼容数据源：已配置 API Key 时优先返回按采样日组装的批次（同形状），失败回退本地
    from .api_answerbit import ab_enabled, ab_runs
    if ab_enabled(db):
        rows = ab_runs(db)
        if rows is not None:
            return rows
    runs = db.query(MonitorRun).filter(MonitorRun.brand_id == brand_id).order_by(MonitorRun.id.desc()).limit(15).all()
    return [_run_dict(r) for r in runs]


@router.get("/monitor/runs/{run_id}")
def get_mrun(run_id: int, db: Session = Depends(get_db)):
    run = db.query(MonitorRun).get(run_id)
    if not run:
        raise HTTPException(404, "采样批次不存在")
    return _run_dict(run)


@router.get("/monitor/samples")
def list_msamples(run_id: int, query_id: Optional[str] = None, db: Session = Depends(get_db)):
    """query_id 可选：不传则返回该批次全部样本（监测中心聚合筛选用）。"""
    # Answerbit 兼容数据源：已配置 API Key 时优先返回该采样日的真实任务样本，失败回退本地
    from .api_answerbit import ab_enabled, ab_samples
    if ab_enabled(db):
        rows = ab_samples(db, run_id, query_id)
        if rows is not None:
            return rows
    q = db.query(MonitorSample).filter(MonitorSample.run_id == run_id)
    if query_id is not None and str(query_id).isdigit():
        q = q.filter(MonitorSample.query_id == int(query_id))
    ss = q.order_by(MonitorSample.id).all()
    return [
        {
            "id": s.id, "run_id": s.run_id, "query_id": s.query_id,
            "engine": s.engine, "market": s.market, "error": s.error,
            "brand_mentioned": s.brand_mentioned, "brand_rank": s.brand_rank,
            "competitors_mentioned": json.loads(s.competitors_mentioned or "[]"),
            "cited_domains": json.loads(s.cited_domains or "[]"),
            "own_domain_cited": s.own_domain_cited,
            "negative_cues": json.loads(s.negative_cues or "[]"),
            "needs_review": s.needs_review, "answer": s.answer,
        }
        for s in ss
    ]


@router.get("/monitor/analysis")
def monitor_analysis(brand_id: int, run_id: Optional[int] = None, db: Session = Depends(get_db)):
    """聚合分析：整体可见性 / 按问题 / 按引擎 / 引用域名 / 竞品，含跨期 delta。"""
    # Answerbit 兼容：AB 批次（yyyymmdd 整数 id）由真实样本聚合出同形状结果，失败回退本地
    from .api_answerbit import ab_analysis, ab_enabled
    if ab_enabled(db) and run_id and run_id > 20250000:
        r = ab_analysis(db, run_id)
        if r is not None:
            return r
    if run_id:
        run = db.query(MonitorRun).get(run_id)
    else:
        run = (
            db.query(MonitorRun)
            .filter(MonitorRun.brand_id == brand_id, MonitorRun.status == "completed")
            .order_by(MonitorRun.id.desc())
            .first()
        )
    if not run or run.status != "completed" or run.brand_id != brand_id:
        return {"has_data": False}

    brand = db.query(Brand).get(brand_id)
    queries = {q.id: q for q in db.query(MonitorQuery).filter(MonitorQuery.brand_id == brand_id).all()}
    samples = db.query(MonitorSample).filter(MonitorSample.run_id == run.id).all()

    # 上一期批次（跨期对比）
    prev = (
        db.query(MonitorRun)
        .filter(MonitorRun.brand_id == brand_id, MonitorRun.status == "completed", MonitorRun.id < run.id)
        .order_by(MonitorRun.id.desc())
        .first()
    )
    prev_rate = {}
    if prev:
        for s in db.query(MonitorSample).filter(MonitorSample.run_id == prev.id).all():
            prev_rate.setdefault(s.query_id, []).append(s)

    # 按问题聚合
    by_query = {}
    for s in samples:
        by_query.setdefault(s.query_id, []).append(s)

    def query_row(qobj, ss):
        valid = [s for s in ss if not s.error]
        mentioned = [s for s in valid if s.brand_mentioned]
        ranks = [s.brand_rank for s in mentioned if s.brand_rank]
        rate = round(100 * len(mentioned) / len(valid)) if valid else None
        row = {
            "id": qobj.id, "question": qobj.question, "qgroup": qobj.qgroup, "market": qobj.market,
            "brand_in_question": qobj.brand_in_question,
            "tags": _parse_tags(qobj.tags),
            "samples": len(valid), "mentioned": len(mentioned), "mention_rate": rate,
            "avg_rank": round(sum(ranks) / len(ranks), 1) if ranks else None,
            "own_domain": any(s.own_domain_cited for s in valid),
            "negative": any(json.loads(s.negative_cues or "[]") for s in valid),
            "needs_review": any(s.needs_review for s in valid),
        }
        pv = [s for s in prev_rate.get(qobj.id, []) if not s.error]
        pm = [s for s in pv if s.brand_mentioned]
        prev_r = round(100 * len(pm) / len(pv)) if pv else None
        row["delta"] = rate - prev_r if (rate is not None and prev_r is not None) else None
        return row

    rows = [query_row(qobj, ss) for qid, ss in by_query.items() if (qobj := queries.get(qid))]
    vis_rows = [r for r in rows if not r["brand_in_question"]]
    ba_rows = [r for r in rows if r["brand_in_question"]]

    # 整体可见性（点名品牌的问题不计入，防 100% 假阳性）
    vis_samples = [s for s in samples if not s.error and s.query_id in queries
                   and not queries[s.query_id].brand_in_question]
    mentioned_all = [s for s in vis_samples if s.brand_mentioned]
    ranks_all = [s.brand_rank for s in mentioned_all if s.brand_rank]
    n = len(vis_samples)
    overall = {
        "samples": n, "mentioned": len(mentioned_all),
        "mention_rate": round(100 * len(mentioned_all) / n) if n else None,
        "top1_rate": round(100 * sum(1 for r in ranks_all if r == 1) / n) if n else None,
        "top3_rate": round(100 * sum(1 for r in ranks_all if r <= 3) / n) if n else None,
        "avg_rank": round(sum(ranks_all) / len(ranks_all), 1) if ranks_all else None,
        "own_domain_rate": round(100 * sum(1 for s in vis_samples if s.own_domain_cited) / n) if n else None,
        "negative": sum(1 for s in vis_samples if json.loads(s.negative_cues or "[]")),
        "needs_review": sum(1 for s in vis_samples if s.needs_review),
    }

    # 按引擎
    by_engine = {}
    for s in vis_samples:
        by_engine.setdefault(s.engine, []).append(s)
    engines = [
        {"name": e, "samples": len(ss), "mentioned": sum(1 for s in ss if s.brand_mentioned),
         "rate": round(100 * sum(1 for s in ss if s.brand_mentioned) / len(ss))}
        for e, ss in sorted(by_engine.items())
    ]

    # 引用域名 Top15 / 竞品提及计数
    from collections import Counter
    domain_counter = Counter()
    comp_counter = Counter()
    for s in vis_samples:
        domain_counter.update(json.loads(s.cited_domains or "[]"))
        comp_counter.update(json.loads(s.competitors_mentioned or "[]"))

    return {
        "has_data": True,
        "run": _run_dict(run),
        "demo": bool(run.demo),
        "brand": {
            "name": brand.name, "domain": brand.domain,
            "aliases": monitor_svc.brand_aliases(brand),
            "competitors": monitor_svc.competitor_names(brand),
        },
        "overall": overall,
        "queries": vis_rows,
        "brand_awareness": ba_rows,
        "engines": engines,
        "citations": [{"domain": d, "count": c} for d, c in domain_counter.most_common(15)],
        "competitors": [{"name": c, "count": n} for c, n in comp_counter.most_common()],
        "errors": sum(1 for s in samples if s.error),
    }
