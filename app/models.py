from datetime import datetime
from typing import Optional

from sqlalchemy import Boolean, DateTime, Float, ForeignKey, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from .database import Base


class Brand(Base):
    """品牌档案：写作时的核心上下文（卖点/调性/竞品/别名）。"""

    __tablename__ = "brands"

    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(100), unique=True)
    company: Mapped[str] = mapped_column(String(200), default="")
    industry: Mapped[str] = mapped_column(String(100), default="")
    # 别名（逗号分隔），供品牌提及判定与知识检索加权
    aliases: Mapped[str] = mapped_column(Text, default="")
    selling_points: Mapped[str] = mapped_column(Text, default="")
    competitors: Mapped[str] = mapped_column(Text, default="")
    tone: Mapped[str] = mapped_column(String(100), default="专业可信")
    # 官方域名（如 xinglan.com），用于判定 AI 回答是否引用了自家信源
    domain: Mapped[str] = mapped_column(String(200), default="")
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)


class Document(Base):
    """知识库文档（粘贴/上传全文，自动分块）。"""

    __tablename__ = "documents"

    id: Mapped[int] = mapped_column(primary_key=True)
    brand_id: Mapped[int] = mapped_column(ForeignKey("brands.id"), index=True)
    title: Mapped[str] = mapped_column(String(200))
    source: Mapped[str] = mapped_column(String(50), default="paste")  # paste/upload/url/knowledge_card
    content: Mapped[str] = mapped_column(Text)
    # 知识卡元数据（JSON）：card_id / topics / quality / status / source_types
    meta: Mapped[str] = mapped_column(Text, default="")
    chunk_count: Mapped[int] = mapped_column(Integer, default=0)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)


class Chunk(Base):
    """知识分块：RAG 检索的最小单元（后续可升级为向量检索）。"""

    __tablename__ = "chunks"

    id: Mapped[int] = mapped_column(primary_key=True)
    document_id: Mapped[int] = mapped_column(ForeignKey("documents.id"), index=True)
    brand_id: Mapped[int] = mapped_column(ForeignKey("brands.id"), index=True)
    seq: Mapped[int] = mapped_column(Integer, default=0)
    text: Mapped[str] = mapped_column(Text)
    # 检索用关键词（小标题 + 首行），逗号分隔
    keywords: Mapped[str] = mapped_column(Text, default="")
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)


class Topic(Base):
    """选题：待生产的 GEO 关键词/问题（8 维 + 3 类意图）。"""

    __tablename__ = "topics"

    id: Mapped[int] = mapped_column(primary_key=True)
    brand_id: Mapped[int] = mapped_column(ForeignKey("brands.id"), index=True)
    keyword: Mapped[str] = mapped_column(String(200))
    # buyer_intent 买家意图 / education 需求教育 / probe 探测
    intent: Mapped[str] = mapped_column(String(50), default="buyer_intent")
    # 8 维：语义泛化/使用场景/商业意图/推荐榜单/评测对比/品牌词/问答长尾/技术方案
    dimension: Mapped[str] = mapped_column(String(50), default="问答长尾")
    market: Mapped[str] = mapped_column(String(20), default="cn")  # cn/global/both
    status: Mapped[str] = mapped_column(String(20), default="pending")  # pending/used
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)


class Article(Base):
    """内容：生成的文章草稿及其审核/发布状态机。"""

    __tablename__ = "articles"

    id: Mapped[int] = mapped_column(primary_key=True)
    brand_id: Mapped[int] = mapped_column(ForeignKey("brands.id"), index=True)
    topic_id: Mapped[int] = mapped_column(ForeignKey("topics.id"), nullable=True)
    title: Mapped[str] = mapped_column(String(300))
    template: Mapped[str] = mapped_column(String(50), default="对比选购")
    body: Mapped[str] = mapped_column(Text)
    # draft/pending_review/approved/published/rejected
    status: Mapped[str] = mapped_column(String(30), default="pending_review", index=True)
    # 证据编号 -> 原文，JSON 数组
    evidence: Mapped[str] = mapped_column(Text, default="")
    # 规则核查结果，JSON 数组 [{type, detail}]
    rule_issues: Mapped[str] = mapped_column(Text, default="[]")
    # AI 审稿结果，JSON {verdict, score, issues, comment}
    ai_review: Mapped[str] = mapped_column(Text, default="{}")
    score: Mapped[float] = mapped_column(Float, nullable=True)
    # 生产方式：ai 生成 / upload 本地上传
    source: Mapped[str] = mapped_column(String(20), default="ai")
    # AI 生成元数据（JSON）：{models: [...], question: "..."}
    gen_meta: Mapped[str] = mapped_column(Text, default="")
    publish_channel: Mapped[str] = mapped_column(String(100), default="")
    published_url: Mapped[str] = mapped_column(String(500), default="")
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)


class Setting(Base):
    """运行时配置（LLM 供应商、发布渠道等），key-value。"""

    __tablename__ = "settings"

    key: Mapped[str] = mapped_column(String(100), primary_key=True)
    value: Mapped[str] = mapped_column(Text, default="")


class CardReview(Base):
    """知识卡人工审核记录：标记（passed/rejected/deleted）+ 备注，按 card_id 存。"""

    __tablename__ = "card_reviews"

    card_id: Mapped[str] = mapped_column(String(50), primary_key=True)
    # passed 已通过 / rejected 已拒绝 / deleted 已删除
    tag: Mapped[str] = mapped_column(String(20), default="passed")
    note: Mapped[str] = mapped_column(Text, default="")
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)


class MonitorQuery(Base):
    """监测问题：定期向 AI 引擎提问的口径（七组 × 市场，点名品牌的归品牌认知）。"""

    __tablename__ = "monitor_queries"

    id: Mapped[int] = mapped_column(primary_key=True)
    brand_id: Mapped[int] = mapped_column(ForeignKey("brands.id"), index=True)
    question: Mapped[str] = mapped_column(String(300))
    # 七组：推荐/比较/替代/价格/风险/品牌验证/场景
    qgroup: Mapped[str] = mapped_column(String(20), default="场景")
    # 八大标签（多选，逗号分隔）：决策机制/关注点/人群/品类/品牌/场景/约束
    tags: Mapped[str] = mapped_column(String(200), default="")
    market: Mapped[str] = mapped_column(String(20), default="cn")  # cn/global
    # 问题中点名了品牌：只算品牌认知，不进可见性指标（防 100% 假阳性）
    brand_in_question: Mapped[bool] = mapped_column(Boolean, default=False)
    active: Mapped[bool] = mapped_column(Boolean, default=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)


class MonitorRun(Base):
    """采样批次：一次「问题 × 引擎」的全量执行。"""

    __tablename__ = "monitor_runs"

    id: Mapped[int] = mapped_column(primary_key=True)
    brand_id: Mapped[int] = mapped_column(ForeignKey("brands.id"), index=True)
    status: Mapped[str] = mapped_column(String(20), default="running")  # running/completed
    # 演示采样批次标志（seed 生成；用户发起的真实采样为 False）
    demo: Mapped[bool] = mapped_column(Boolean, default=False)
    total: Mapped[int] = mapped_column(Integer, default=0)
    done: Mapped[int] = mapped_column(Integer, default=0)
    started_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    finished_at: Mapped[datetime] = mapped_column(DateTime, nullable=True)


class MonitorSample(Base):
    """单条采样：某引擎对某问题的一句回答及其提及判定结果。"""

    __tablename__ = "monitor_samples"

    id: Mapped[int] = mapped_column(primary_key=True)
    run_id: Mapped[int] = mapped_column(ForeignKey("monitor_runs.id"), index=True)
    query_id: Mapped[int] = mapped_column(ForeignKey("monitor_queries.id"), index=True)
    engine: Mapped[str] = mapped_column(String(100), default="")
    market: Mapped[str] = mapped_column(String(20), default="cn")
    answer: Mapped[str] = mapped_column(Text, default="")
    error: Mapped[str] = mapped_column(Text, default="")
    brand_mentioned: Mapped[bool] = mapped_column(Boolean, default=False)
    brand_rank: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    # JSON 数组：出现的竞品名
    competitors_mentioned: Mapped[str] = mapped_column(Text, default="[]")
    # JSON 数组：回答中引用的域名
    cited_domains: Mapped[str] = mapped_column(Text, default="[]")
    own_domain_cited: Mapped[bool] = mapped_column(Boolean, default=False)
    # JSON 数组：疑似负面线索词
    negative_cues: Mapped[str] = mapped_column(Text, default="[]")
    needs_review: Mapped[bool] = mapped_column(Boolean, default=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
