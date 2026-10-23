"""知识库：文档分块 + 关键词检索（RAG 简版，留向量升级位）。

分块策略借鉴 GEOFlow 的「结构化规则切片」：优先按标题（#/##/###）切，
无标题时按空行段落合并到 ~600 字。
"""
from typing import List

from sqlalchemy.orm import Session

from ..models import Brand, Chunk, Document

CHUNK_SIZE = 600


def split_content(content: str) -> List[dict]:
    """结构化分块，返回 [{text, keywords}]。"""
    lines = content.splitlines()
    sections: List[List[str]] = [[]]
    for line in lines:
        if line.strip().startswith("#") and any(sections[-1]):
            sections.append([])
        sections[-1].append(line)

    chunks: List[dict] = []
    for section in sections:
        text = "\n".join(section).strip()
        if not text:
            continue
        heading = next((l for l in section if l.strip().startswith("#")), section[0])
        keywords = heading.strip().lstrip("#").strip()[:60]
        if len(text) <= CHUNK_SIZE:
            chunks.append({"text": text, "keywords": keywords})
        else:
            # 长段落二次切分
            for i in range(0, len(text), CHUNK_SIZE):
                chunks.append({"text": text[i : i + CHUNK_SIZE], "keywords": keywords})
    if not chunks:
        chunks.append({"text": content.strip()[:CHUNK_SIZE], "keywords": ""})
    return chunks


def build_chunks(db: Session, doc: Document) -> int:
    """重建文档分块，返回分块数。"""
    db.query(Chunk).filter(Chunk.document_id == doc.id).delete()
    parts = split_content(doc.content)
    for seq, part in enumerate(parts):
        db.add(Chunk(document_id=doc.id, brand_id=doc.brand_id, seq=seq, text=part["text"], keywords=part["keywords"]))
    doc.chunk_count = len(parts)
    db.commit()
    return len(parts)


def _score(chunk: Chunk, keyword: str, aliases: List[str]) -> int:
    s = 0
    if keyword:
        s += chunk.text.count(keyword) * 3
        # 2-gram 覆盖（中文关键词常无空格分词）
        grams = {keyword[i : i + 2] for i in range(len(keyword) - 1)} if len(keyword) > 2 else {keyword}
        for g in grams:
            s += chunk.text.count(g)
    for a in aliases:
        if a and a in chunk.text:
            s += 2
    if keyword and keyword in chunk.keywords:
        s += 5
    return s


def retrieve(db: Session, brand: Brand, keyword: str, top_k: int = 6) -> List[Chunk]:
    """按选题关键词 + 品牌别名对分块打分，取 Top-K 作为生成证据。"""
    chunks = db.query(Chunk).filter(Chunk.brand_id == brand.id).all()
    if not chunks:
        return []
    aliases = [a.strip() for a in (brand.aliases or "").split(",") if a.strip()]
    aliases.append(brand.name)
    scored = sorted(chunks, key=lambda c: _score(c, keyword, aliases), reverse=True)
    scored = [c for c in scored if _score(c, keyword, aliases) > 0] or scored
    return scored[:top_k]
