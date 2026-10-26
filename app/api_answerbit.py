"""Answerbit 适配路由：配置管理 + 连接测试 + 全接口透传 + 核心场景映射。

设计原则（协议先行的兼容适配）：
- 未配置 API Key 时：映射端点返回 409，提示先配置；`/call` 同样 409；
- `POST /api/answerbit/call`：全 95 接口通用透传（path + payload），协议保底；
- 核心场景（监测中心/回答记录/选题库/内容工厂）提供语义化映射端点，
  字段尽量贴近产品现有形状，同时保留 `raw` 原始数据避免信息丢失。
"""
from __future__ import annotations

import json
import re
import threading
import time
import time as _time  # noqa: F401  （monitor-view/compat 缓存时间戳用）
from pathlib import Path
from datetime import date, timedelta
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy.orm import Session

from .answerbit import (
    AnswerbitClient, ApiError, AuthError, ConfigError, NetworkError,
    get_client, load_config, mask_key, save_config,
)
from .database import get_db

router = APIRouter(prefix="/answerbit")


def _err(status: int, exc: Exception) -> HTTPException:
    msg = str(exc)
    if isinstance(exc, ConfigError):
        status = 409
    elif isinstance(exc, AuthError):
        status = 401
    elif isinstance(exc, NetworkError):
        status = 502
    elif isinstance(exc, ApiError):
        status = 502 if exc.code < 0 else 400
    return HTTPException(status, msg)


def _client(db: Session) -> AnswerbitClient:
    try:
        return get_client(db)
    except ConfigError as e:
        raise _err(409, e)


def _daterange(begin: Optional[str], end: Optional[str]) -> tuple[str, str]:
    """日期区间缺省取最近 7 天（含今天）。Answerbit 要求 begin/end 成对必传。"""
    end_d = date.fromisoformat(end) if end else date.today()
    begin_d = date.fromisoformat(begin) if begin else end_d - timedelta(days=6)
    return begin_d.isoformat(), end_d.isoformat()


# ---------- schemas ----------

class ConfigIn(BaseModel):
    api_key: Optional[str] = None
    base_url: Optional[str] = None
    team_id: Optional[str] = None
    brand_id: Optional[str] = None


class CallIn(BaseModel):
    # 以 /geo 开头的完整接口路径，如 /geo/article/get
    path: str
    payload: Dict[str, Any] = {}


class GenerateIn(BaseModel):
    template_type: str = ""
    prompt_ids: List[str] = []
    knowledge_ids: List[str] = []
    # 仿写范文：{"url": ...} 或 {"title": ..., "content": ...}
    high_ref: Optional[Dict[str, Any]] = None
    tag_ids: List[str] = []
    language: str = "zh"
    brand_id: Optional[str] = None


class UploadIn(BaseModel):
    # 文档字段（title/main_body 等）以 Answerbit /geo/article/upload 协议为准，整体透传
    payload: Dict[str, Any]
    brand_id: Optional[str] = None


# ---------- 配置管理 ----------

@router.get("/status")
def status(db: Session = Depends(get_db)):
    cfg = load_config(db)
    return {
        "configured": bool(cfg["api_key"]),
        "has_team": bool(cfg["team_id"]),
        "has_brand": bool(cfg["brand_id"]),
        "base_url": cfg["base_url"],
        "api_key_masked": mask_key(cfg["api_key"]),
    }


@router.get("/config")
def get_config(db: Session = Depends(get_db)):
    cfg = load_config(db)
    return {
        "api_key": mask_key(cfg["api_key"]),
        "has_api_key": bool(cfg["api_key"]),
        "base_url": cfg["base_url"],
        "team_id": cfg["team_id"],
        "brand_id": cfg["brand_id"],
    }


@router.put("/config")
def put_config(payload: ConfigIn, db: Session = Depends(get_db)):
    save_config(db, payload.model_dump())
    return get_config(db)


@router.post("/config/test")
def test_connection(db: Session = Depends(get_db)):
    """连接测试：优先 /geo/team/get/filter_platforms（需要 team_id），失败回退 /geo/query/brand。"""
    client = _client(db)
    t0 = time.monotonic()
    try:
        result: Dict[str, Any] = {"ok": True, "latency_ms": None, "probe": "", "detail": None}
        try:
            platforms = client.filter_platforms()
            result["probe"] = "/geo/team/get/filter_platforms"
            result["detail"] = {"platforms": platforms}
        except (ConfigError, ApiError):
            brands = client.brand_list()
            result["probe"] = "/geo/query/brand"
            result["detail"] = {"brands": brands}
        result["latency_ms"] = round((time.monotonic() - t0) * 1000)
        return result
    except (ConfigError, AuthError, ApiError, NetworkError) as e:
        raise _err(400, e)


# ---------- 通用透传（协议保底，95 接口全可用） ----------

@router.post("/call")
def generic_call(payload: CallIn, db: Session = Depends(get_db)):
    client = _client(db)
    try:
        # 便利性补全：绝大多数 /geo 接口需要 brand_id / team_id；
        # 仅当调用方未显式传入时补默认配置值（多余字段平台一般忽略，显式值优先）
        merged = dict(payload.payload or {})
        if "brand_id" not in merged and client.brand_id:
            merged["brand_id"] = client.brand_id
        if "team_id" not in merged and client.team_id:
            merged["team_id"] = client.team_id
        return {"ok": True, "data": client.call(payload.path, merged)}
    except (ConfigError, AuthError, ApiError, NetworkError) as e:
        raise _err(400, e)


# ---------- 监测中心映射 ----------

@router.get("/dashboard")
def dashboard(begin_date: Optional[str] = None, end_date: Optional[str] = None,
              platforms: Optional[str] = None, title_ids: Optional[str] = None,
              tag_ids: Optional[str] = None, db: Session = Depends(get_db)):
    """指标卡：提及率/平均排名/曝光效果分数（含环比 fluctuation）。"""
    client = _client(db)
    b, e = _daterange(begin_date, end_date)
    try:
        raw = client.dashboard(
            begin_date=b, end_date=e,
            platforms=(platforms or "").split(",") if platforms else [],
            title_ids=(title_ids or "").split(",") if title_ids else [],
            tag_ids=(tag_ids or "").split(",") if tag_ids else [],
        )
    except (ConfigError, AuthError, ApiError, NetworkError) as ex:
        raise _err(400, ex)
    # 映射为扁平结构 + 保留 raw
    exposure = raw.get("exposure") or {}
    avg_rank = raw.get("avg_rank") or {}
    score = raw.get("score") or {}
    return {
        "begin_date": b, "end_date": e,
        "mention_rate": exposure.get("value"),
        "mention_rate_delta": exposure.get("fluctuation"),
        "avg_rank": avg_rank.get("value"),
        "avg_rank_delta": avg_rank.get("fluctuation"),
        "score": score.get("value"),
        "score_delta": score.get("fluctuation"),
        "raw": raw,
    }


@router.get("/exposure-trends")
def exposure_trends(begin_date: Optional[str] = None, end_date: Optional[str] = None,
                    competitor_ids: Optional[str] = None,
                    platforms: Optional[str] = None,
                    title_ids: Optional[str] = None, db: Session = Depends(get_db)):
    """提及率/平均排名按日趋势曲线（可带竞品同期曲线），供监测中心曲线图。"""
    client = _client(db)
    b, e = _daterange(begin_date, end_date)
    try:
        raw = client.exposure_trends(
            begin_date=b, end_date=e,
            competitor_ids=(competitor_ids or "").split(",") if competitor_ids else [],
            platforms=(platforms or "").split(",") if platforms else [],
            title_ids=(title_ids or "").split(",") if title_ids else [],
        )
    except (ConfigError, AuthError, ApiError, NetworkError) as ex:
        raise _err(400, ex)
    # 品牌按日序列 → points[{date, mention_rate, avg_rank, task_count}]
    points = [
        {
            "date": row.get("date"),
            "mention_rate": row.get("exposure"),
            "avg_rank": row.get("avg_rank"),
            "task_count": row.get("task_count"),
        }
        for row in raw.get("brand_statistics") or []
    ]
    competitors = [
        {
            "competitor_id": c.get("competitor_id"), "name": c.get("name"),
            "points": [
                {"date": s.get("date"), "mention_rate": s.get("exposure"),
                 "avg_rank": s.get("avg_rank"), "task_count": s.get("task_count")}
                for s in c.get("statistics") or []
            ],
        }
        for c in raw.get("competitor_statistics") or []
    ]
    return {"begin_date": b, "end_date": e, "points": points, "competitors": competitors, "raw": raw}


@router.get("/competitor-rank")
def competitor_rank(begin_date: Optional[str] = None, end_date: Optional[str] = None,
                    metric: str = "exposure", platforms: Optional[str] = None,
                    db: Session = Depends(get_db)):
    """竞品对比：metric=exposure（提及率，默认）或 score（曝光效果分数）。"""
    client = _client(db)
    b, e = _daterange(begin_date, end_date)
    try:
        if metric == "score":
            raw = client.score_rank(begin_date=b, end_date=e,
                                    platforms=(platforms or "").split(",") if platforms else [])
        else:
            raw = client.exposure_rank(begin_date=b, end_date=e,
                                        platforms=(platforms or "").split(",") if platforms else [])
    except (ConfigError, AuthError, ApiError, NetworkError) as ex:
        raise _err(400, ex)
    rows = []
    for item in raw or []:
        is_brand = str(item.get("competitor_id")) == "0"
        row = {
            "id": item.get("competitor_id"), "name": item.get("competitor_name"),
            "is_brand": is_brand,
            "value": item.get("score") if metric == "score" else item.get("exposure"),
            "delta": item.get("fluctuation"),
        }
        if metric != "score":
            ar = item.get("avg_rank") or {}
            row["avg_rank"] = ar.get("value")
            row["avg_rank_delta"] = ar.get("fluctuation")
        rows.append(row)
    rows.sort(key=lambda r: (not r["is_brand"], -(r["value"] or 0)))
    return {"begin_date": b, "end_date": e, "metric": metric, "rows": rows, "raw": raw}


@router.get("/citation-ranks")
def citation_ranks(begin_date: Optional[str] = None, end_date: Optional[str] = None,
                    page: int = 1, page_size: int = 10, db: Session = Depends(get_db)):
    """引用域名排行 + 引用文章排行（监测中心引用来源模块）。"""
    client = _client(db)
    b, e = _daterange(begin_date, end_date)
    try:
        domains = client.domain_rank(begin_date=b, end_date=e, page=page, page_size=page_size)
        articles = client.article_rank(begin_date=b, end_date=e, page=page, page_size=page_size)
    except (ConfigError, AuthError, ApiError, NetworkError) as ex:
        raise _err(400, ex)
    return {
        "begin_date": b, "end_date": e,
        "domains": [
            {"domain": d.get("domain"), "count": d.get("count"), "is_own": d.get("is_own")}
            for d in domains.get("reference_count") or []
        ],
        "domains_total": domains.get("total"),
        "articles": [
            {"title": a.get("article"), "url": a.get("url"), "domain": a.get("domain"),
             "count": a.get("count"), "source": a.get("source"), "article_id": a.get("article_id")}
            for a in articles.get("reference_count") or []
        ],
        "articles_total": articles.get("total"),
    }


# ---------- 回答记录映射 ----------

def _answer_row(s: Dict[str, Any]) -> Dict[str, Any]:
    """task/get scores 行 → 产品回答记录形状（monitor sample 兼容）。"""
    return {
        "task_id": s.get("task_id"),
        "query_id": s.get("query_id") or s.get("prompt_id"),
        "question": s.get("query_str"),
        "engine": s.get("platform"),
        "market": s.get("zone"),
        "date": s.get("date"),
        "brand_mentioned": bool(s.get("exposure")),
        "brand_rank": s.get("avg_rank") or None,
        "score": s.get("score"),
        "title_id": s.get("title_id"),
        "title_name": s.get("title_name"),
        "tags": [t.get("tag_name") for t in s.get("tags") or []],
        "trace_article_cnt": s.get("trace_article_cnt"),
        "raw": s,
    }


@router.get("/answers")
def answers(begin_date: Optional[str] = None, end_date: Optional[str] = None,
            mention_brand: int = -1, platforms: Optional[str] = None,
            query_str: str = "", min_score: Optional[int] = None,
            max_score: Optional[int] = None, page: int = 1, page_size: int = 20,
            db: Session = Depends(get_db)):
    """回答记录列表（提及/评分/平台/关键字筛选）。"""
    client = _client(db)
    b, e = _daterange(begin_date, end_date)
    try:
        raw = client.task_list(
            begin_date=b, end_date=e, mention_brand=mention_brand,
            platforms=(platforms or "").split(",") if platforms else [],
            prompt=query_str, min_score=min_score, max_score=max_score,
            page=page, page_size=page_size)
    except (ConfigError, AuthError, ApiError, NetworkError) as ex:
        raise _err(400, ex)
    return {
        "begin_date": b, "end_date": e, "total": raw.get("total"),
        "items": [_answer_row(s) for s in raw.get("scores") or []],
    }


@router.get("/answers/{task_id}")
def answer_detail(task_id: str, brand_id: Optional[str] = None,
                  db: Session = Depends(get_db)):
    """回答详情：原文、引用链接、图片、推荐提问、视频/商品卡。"""
    client = _client(db)
    try:
        raw = client.task_detail(brand_id=brand_id or "", task_id=task_id)
    except (ConfigError, AuthError, ApiError, NetworkError) as ex:
        raise _err(400, ex)
    links = raw.get("links") or []
    cited_domains = sorted({str(l.get("url") or "").split("/")[2]
                            for l in links if "://" in str(l.get("url") or "")})
    return {
        "task_id": task_id,
        "question": raw.get("prompt") or raw.get("query"),
        "query_id": raw.get("prompt_id") or raw.get("query_id"),
        "answer": raw.get("llm_output"),
        "engine": raw.get("platform"),
        "date": raw.get("date"),
        "brand_mentioned": bool(raw.get("exposure")),
        "brand_rank": raw.get("rank") or None,
        "mention_count": raw.get("exposure_cnt"),
        "cited_domains": cited_domains,
        "links": links,
        "pics": raw.get("pic") or [],
        "recommend_queries": raw.get("recommend_queries") or [],
        "video_cards": raw.get("video_cards") or [],
        "product_cards": raw.get("product_cards") or [],
        "raw": raw,
    }


# ---------- 选题库映射 ----------

_QTYPE_INTENT = {1: "education", 2: "buyer_intent"}


def _topic_row(item: Dict[str, Any]) -> Dict[str, Any]:
    """推荐选题 → 产品 Topic 兼容形状。"""
    status = str(item.get("status") or "")
    return {
        "id": item.get("id"),
        "keyword": item.get("question_text"),
        "original_keyword": item.get("original_question_text"),
        "intent": _QTYPE_INTENT.get(int(item.get("question_type") or 0), "buyer_intent"),
        "dimension": item.get("knowledge_dimension") or "",
        "heat_score": item.get("heat_score"),
        "avg_rank": item.get("avg_rank"),
        "source_platforms": (item.get("source_platforms") or "").split(",") if item.get("source_platforms") else [],
        "source_count": item.get("source_count"),
        "status": "pending" if status == "PENDING" else "used",
        "rec_status": status,
        "monitor_query_id": item.get("monitor_query_id") or "",
        "raw": item,
    }


@router.get("/recommendations")
def recommendations(question_type: int = 0, status: str = "", sort_by: str = "",
                    min_heat_score: Optional[float] = None, page: int = 1,
                    page_size: int = 20, db: Session = Depends(get_db)):
    """推荐选题列表（question_type: 0全部/1基建型/2触发型；status: PENDING/CONFIRMED/EDITED）。"""
    client = _client(db)
    try:
        raw = client.recommendation_list(
            question_type=question_type, status=status, sort_by=sort_by,
            min_heat_score=min_heat_score, page=page, page_size=page_size)
    except (ConfigError, AuthError, ApiError, NetworkError) as ex:
        raise _err(400, ex)
    return {"total": raw.get("total"), "items": [_topic_row(i) for i in raw.get("list") or []]}


@router.post("/recommendations/trigger")
def recommendations_trigger(target_date: Optional[str] = None,
                            db: Session = Depends(get_db)):
    """异步触发推荐选题生成（稍后轮询 recommendations 列表）。"""
    client = _client(db)
    try:
        raw = client.recommendation_trigger(target_date=target_date or "")
    except (ConfigError, AuthError, ApiError, NetworkError) as ex:
        raise _err(400, ex)
    return {"ok": True, "status": (raw or {}).get("status", "processing"), "raw": raw}


@router.post("/recommendations/{rid}/confirm")
def recommendation_confirm(rid: str, db: Session = Depends(get_db)):
    """确认推荐选题 → 平台自动创建监控提问，返回 monitor_query_id。"""
    client = _client(db)
    try:
        raw = client.recommendation_confirm(rid)
    except (ConfigError, AuthError, ApiError, NetworkError) as ex:
        raise _err(400, ex)
    return {
        "ok": True,
        "recommendation_id": (raw or {}).get("recommendation_id", rid),
        "monitor_query_id": (raw or {}).get("monitor_query_id"),
        "status": (raw or {}).get("status"),
        "raw": raw,
    }


# ---------- 内容工厂映射 ----------

_ARTICLE_STATUS = {0: "draft", 1: "pending_review", 2: "approved", 3: "published", 4: "rejected"}
_ARTICLE_STATUS_LABELS = {0: "生成中", 1: "待发布", 2: "发布中", 3: "追踪中", 4: "失败"}


@router.post("/articles/generate")
def articles_generate(payload: GenerateIn, db: Session = Depends(get_db)):
    """提交 AI 生成任务（异步受理）：模板化 / 仿写范文（high_ref）/ 关联选题与知识。"""
    client = _client(db)
    try:
        raw = client.article_create(
            brand_id=payload.brand_id or "", template_type=payload.template_type,
            prompt_ids=payload.prompt_ids, knowledge_ids=payload.knowledge_ids,
            high_ref=payload.high_ref, tag_ids=payload.tag_ids, language=payload.language)
    except (ConfigError, AuthError, ApiError, NetworkError) as ex:
        raise _err(400, ex)
    return {"ok": True, "accepted": True, "data": raw}


@router.post("/articles/upload")
def articles_upload(payload: UploadIn, db: Session = Depends(get_db)):
    """本地上传/粘贴正文直接录入（payload 字段以 /geo/article/upload 协议为准，整体透传）。"""
    client = _client(db)
    try:
        raw = client.article_upload(brand_id=payload.brand_id or "", **payload.payload)
    except (ConfigError, AuthError, ApiError, NetworkError) as ex:
        raise _err(400, ex)
    return {"ok": True, "data": raw}


def _article_dict(raw: Dict[str, Any]) -> Dict[str, Any]:
    status = int(raw.get("status", 1) or 1)
    return {
        "id": raw.get("id"),
        "title": raw.get("title"),
        "body": raw.get("main_body") or raw.get("body") or "",
        "status": _ARTICLE_STATUS.get(status, str(status)),
        "status_label": _ARTICLE_STATUS_LABELS.get(status, str(status)),
        "raw_status": status,
        "raw": raw,
    }


@router.get("/articles/{article_id}")
def article_detail(article_id: str, brand_id: Optional[str] = None,
                   db: Session = Depends(get_db)):
    """查询单篇文章（生成状态轮询：0生成中/1待发布/2发布中/3追踪中/4失败）。"""
    client = _client(db)
    try:
        raw = client.article_get(brand_id=brand_id or "", article_id=article_id)
    except (ConfigError, AuthError, ApiError, NetworkError) as ex:
        raise _err(400, ex)
    return _article_dict(raw or {})


@router.get("/articles")
def articles(page: int = 1, page_size: int = 20, db: Session = Depends(get_db)):
    """文章列表 + 引用汇总（游标分页，参数透传见 /geo/article/query）。"""
    client = _client(db)
    try:
        raw = client.article_query(page=page, page_size=page_size)
    except (ConfigError, AuthError, ApiError, NetworkError) as ex:
        raise _err(400, ex)
    return {"ok": True, "data": raw}


@router.post("/articles/{article_id}/distribute")
def article_distribute(article_id: str, payload: Dict[str, Any],
                       db: Session = Depends(get_db)):
    """提交文章自动发布（payload 以 /geo/article/distribute 协议为准）。"""
    client = _client(db)
    try:
        payload.setdefault("id", article_id)
        raw = client.distribute(**payload)
    except (ConfigError, AuthError, ApiError, NetworkError) as ex:
        raise _err(400, ex)
    return {"ok": True, "data": raw}


# ---------- 品牌与平台数据（接入初始化） ----------

@router.get("/brands")
def brands(db: Session = Depends(get_db)):
    """列出 Answerbit 团队下的品牌（供配置默认 brand_id）。"""
    client = _client(db)
    try:
        raw = client.brand_list()
    except (ConfigError, AuthError, ApiError, NetworkError) as ex:
        raise _err(400, ex)
    return {"ok": True, "data": raw}


# ---------- 监测中心聚合视图 ----------

_RAGG_TTL = 3600  # rank 聚合缓存 1 小时（全量拉取较慢）
_ragg_cache: Dict[str, Any] = {"key": None, "ts": 0.0, "data": None}
_ragg_lock = threading.Lock()


def _rank_aggregate(client: AnswerbitClient, b: str, e: str) -> Dict[str, Any]:
    """首推率/前三位率/引擎提及率聚合：分母取全量 total，分子从提及样本分页统计。

    Answerbit 未提供 top1/top3 口径接口，需按 task/get 的 avg_rank 分布自算；
    结果缓存 1 小时（提及样本量大，全量拉取约 10-30s）。
    """
    key = f"{client.brand_id}:{b}:{e}"
    with _ragg_lock:
        if _ragg_cache["key"] == key and _time.time() - _ragg_cache["ts"] < _RAGG_TTL:
            return _ragg_cache["data"]
        total = int((client.task_list(begin_date=b, end_date=e, page=1, page_size=1) or {}).get("total") or 0)
        mentioned_total = int((client.task_list(begin_date=b, end_date=e, mention_brand=1,
                                                page=1, page_size=1) or {}).get("total") or 0)
        top1 = top3 = 0
        by_engine: Dict[str, int] = {}
        fetched, page = 0, 1
        while fetched < mentioned_total and page <= 120:
            d = client.task_list(begin_date=b, end_date=e, mention_brand=1,
                                 page=page, page_size=100) or {}
            scores = d.get("scores") or []
            if not scores:
                break
            for s in scores:
                r = int(s.get("avg_rank") or 0)
                if r == 1:
                    top1 += 1
                if 1 <= r <= 3:
                    top3 += 1
                eng = s.get("platform")
                if eng:
                    by_engine[eng] = by_engine.get(eng, 0) + 1
            fetched += len(scores)
            page += 1
        engines = []
        for eng, m in by_engine.items():
            tot = int((client.task_list(begin_date=b, end_date=e, platforms=[eng],
                                        page=1, page_size=1) or {}).get("total") or 0)
            engines.append({"name": eng, "samples": tot, "mentioned": m,
                            "rate": round(100 * m / tot, 1) if tot else None})
        engines.sort(key=lambda x: -(x["rate"] or 0))
        data = {
            "total": total, "mentioned_total": mentioned_total, "estimated": fetched < mentioned_total,
            "top1_rate": round(1000 * top1 / total) / 10 if total else 0,
            "top3_rate": round(1000 * top3 / total) / 10 if total else 0,
            "engines": engines,
        }
        _ragg_cache.update({"key": key, "ts": _time.time(), "data": data})
        return data


@router.get("/monitor-view")
def monitor_view(begin_date: Optional[str] = None, end_date: Optional[str] = None,
                 db: Session = Depends(get_db)):
    """监测中心整体视图：KPI 四口径 + 趋势 + 竞品 + 引用 + 引擎 + 问题明细（近 7 天）。"""
    client = _client(db)
    b, e = _daterange(begin_date, end_date)
    try:
        dash = client.dashboard(begin_date=b, end_date=e) or {}
        rank = client.exposure_rank(begin_date=b, end_date=e) or []
        comp_ids = [str(r.get("competitor_id")) for r in rank
                    if str(r.get("competitor_id")) != "0"][:3]
        trends = client.exposure_trends(begin_date=b, end_date=e, competitor_ids=comp_ids) or {}
        domains = client.domain_rank(begin_date=b, end_date=e, page=1, page_size=15) or {}
        group = client.prompt_get_group(begin_date=b, end_date=e) or {}
        agg = _rank_aggregate(client, b, e)
    except (ConfigError, AuthError, ApiError, NetworkError) as ex:
        raise _err(400, ex)
    # KPI：提及率/引用份额/首推率/前三位率（产品四口径）
    doms = domains.get("reference_count") or []
    tot_c = sum(int(x.get("count") or 0) for x in doms)
    own_c = sum(int(x.get("count") or 0) for x in doms if x.get("is_own"))
    exposure = dash.get("exposure") or {}
    avg_rank = dash.get("avg_rank") or {}
    score = dash.get("score") or {}
    kpi = {
        "mention_rate": exposure.get("value"), "mention_delta": exposure.get("fluctuation"),
        "cite_share": round(1000 * own_c / tot_c) / 10 if tot_c else 0,
        "top1_rate": agg["top1_rate"], "top3_rate": agg["top3_rate"],
        "avg_rank": avg_rank.get("value"), "avg_rank_delta": avg_rank.get("fluctuation"),
        "score": score.get("value"), "score_delta": score.get("fluctuation"),
        "samples": agg["total"], "estimated": agg["estimated"],
    }
    # 趋势点
    points = [{"date": (r.get("date") or "")[5:], "mention_rate": r.get("exposure"),
               "avg_rank": r.get("avg_rank"), "task_count": r.get("task_count")}
              for r in trends.get("brand_statistics") or []]
    competitors = [{"id": c.get("competitor_id"), "name": c.get("name"),
                    "points": [{"date": (s.get("date") or "")[5:], "mention_rate": s.get("exposure")}
                               for s in c.get("statistics") or []]}
                   for c in trends.get("competitor_statistics") or []]
    # 竞品提及率排行
    rank_rows = []
    for r in rank:
        is_brand = str(r.get("competitor_id")) == "0"
        rank_rows.append({"name": r.get("competitor_name"), "is_brand": is_brand,
                          "rate": r.get("exposure"),
                          "avg_rank": (r.get("avg_rank") or {}).get("value")})
    rank_rows.sort(key=lambda x: (not x["is_brand"], -(x["rate"] or 0)))
    # 问题明细（prompt_get_group：分组+提及率+平均排名）
    qrows = []
    for t in group.get("titles") or []:
        for q in t.get("prompts") or []:
            qrows.append({"id": q.get("id"), "question": q.get("query_str"),
                          "qgroup": t.get("title_name"),
                          "mention_rate": round(float(q["exposure"]), 1) if q.get("exposure") is not None else None,
                          "avg_rank": q.get("avg_rank")})
    qrows = [r for r in qrows if r["question"]]
    return {
        "has_data": bool(agg["total"] or points),
        "begin_date": b, "end_date": e,
        "kpi": kpi,
        "trend": {"points": points, "competitors": competitors},
        "engines": agg["engines"],
        "citations": [{"domain": x.get("domain"), "count": x.get("count"),
                       "is_own": x.get("is_own")} for x in doms],
        "competitors_rank": rank_rows,
        "qrows": qrows,
    }


# ---------- 本地 API 兼容适配（前端零改动：/api/monitor/* 双数据源） ----------
# 设计：已配置 Answerbit Key 时，本地 monitor 端点返回由 Answerbit 真实数据组装的同形状响应；
# Answerbit 请求失败自动回退本地演示数据，无 Key 走原逻辑。
#
# 已知口径（修复过的问题）：
# 1. AB 的 64 位 ID 以字符串返回会导致前端模板 `${id}` 内嵌 JS 裸数字字面量精度丢失
#    （多选对勾失效等），故全部映射为安全 int；
# 2. 提问标签来自 prompt_get 的 tags 数组（前端 tagPairs 兼容数组形状）；
# 3. 竞品曲线：task 行无竞品明细，用 exposure/trends 的竞品当日提及率按比例标记当日样本
#    （曲线比率真实，样本级分布为按率的确定性分配）；
# 4. 回答原文：每批次样本量 25 条，ab_samples 首次服务该批次时懒加载 task_detail 的 llm_output
#    并写缓存（全局信号量限 3 并发防平台限流）；
# 5. /api/monitor/analysis 与 PATCH/DELETE /monitor/queries 同步适配（选题库洞察/回答记录按钮依赖）；
# 6. topics 不注入推荐选题（保持本地表现，避免 orphan 区布局异常）。

_compat_cache: Dict[str, Any] = {"key": None, "ts": 0.0, "data": None}
_analysis_cache: Dict[str, Any] = {}  # {brand:day: {"ts", "rows"}} 批次问题指标行缓存
_compat_ttl = 3600
_detail_sem = threading.Semaphore(3)   # task_detail 全局并发上限（防平台限流）
_compat_lock = threading.RLock()

_BATCH_SIZE = 25  # 每个采样日注入的样本条数（明细完整性与加载耗时的平衡）

# 平台原始 platform 值 → 产品模型名（与前端 MON_MODELS 对齐；监测中心模型筛选依赖同名匹配）
_ENGINE_MAP = {
    "deepseek": "DeepSeek", "doubao": "豆包", "qianwen": "千问",
    "qwen": "千问", "yuanbao": "元宝",
}


# ---------- 词包标签（GEO 词包 xlsx → wordpack_tags.json，7 维标签字典） ----------
# 平台侧提问未打业务标签，此处按归一化文本匹配词包，命中返回 {维度: 值} dict，
# 未命中返回 []（前端 tagChips/hasTagDim 同时兼容 dict 与数组形状）。
_WORDPACK_FILE = Path(__file__).resolve().parent / "wordpack_tags.json"
_wordpack_cache: Optional[Dict[str, Dict[str, str]]] = None


def _wp_norm(s: str) -> str:
    return re.sub(r"\s+", "", s or "")


def _wp_tags(question: str):
    global _wordpack_cache
    if _wordpack_cache is None:
        try:
            with open(_WORDPACK_FILE, encoding="utf-8") as f:
                _wordpack_cache = {_wp_norm(k): v for k, v in (json.load(f) or {}).items()}
        except Exception:
            _wordpack_cache = {}
    return _wordpack_cache.get(_wp_norm(question)) or []


def ab_enabled(db) -> bool:
    """是否启用 Answerbit 兼容数据源（配置了 API Key 即启用）。"""
    try:
        return bool(load_config(db)["api_key"])
    except Exception:
        return False


def _brand_name(db) -> str:
    """本地平台档案品牌名（用于「点名品牌的提问」判定，不硬编码具体品牌）。"""
    try:
        from .models import Brand
        b = db.query(Brand).first()
        return (b.name if b else "") or ""
    except Exception:
        return ""


def _brand_domain(db) -> str:
    """本地平台档案官方域名（用于引用域名归属判定）。"""
    try:
        from .models import Brand
        b = db.query(Brand).first()
        return (b.domain if b else "") or ""
    except Exception:
        return ""


def _compat_build(client: AnswerbitClient, brand_name: str = "") -> Dict[str, Any]:
    """组装与本地 API 相同形状的 queries/runs/samples（缓存 1 小时）。"""
    key = f"{client.brand_id}"
    with _compat_lock:
        if _compat_cache["key"] == key and _time.time() - _compat_cache["ts"] < _compat_ttl:
            return _compat_cache["data"]

        from datetime import date as _date, timedelta as _td

        # 1) 提问列表：prompt_get 分页拉取（含 tags/title_name/status）
        queries, idmap = [], {}
        next_int = [100000001]
        page = 1
        while True:
            try:
                pg = client.prompt_get(page=page, page_size=50) or {}
            except (ApiError, AuthError, NetworkError):
                break
            rows = pg.get("prompts") or []
            if not rows:
                break
            for q in rows:
                pid = str(q.get("prompt_id") or "")
                qstr = q.get("query_str") or ""
                if not pid or not qstr or pid in idmap:
                    continue
                qid = next_int[0]
                next_int[0] += 1
                idmap[pid] = qid
                queries.append({
                    "id": qid, "question": qstr, "qgroup": q.get("title_name") or "",
                    "market": "", "brand_in_question": bool(brand_name) and brand_name in qstr,
                    "active": int(q.get("status") or 1) == 1,
                    "tags": _wp_tags(qstr),
                    "_ab_id": pid,
                })
            if len(rows) < 50:
                break
            page += 1

        # 2) 每日样本：近 7 天每天最新 _BATCH_SIZE 条
        #    平台原始 platform 值归一为产品模型名（与前端 MON_MODELS 一致），kimi 不注入
        samples = []
        day_samples: Dict[str, list] = {}
        for i in range(7):
            day = (_date.today() - _td(days=i)).isoformat()
            try:
                d = client.task_list(begin_date=day, end_date=day, page=1,
                                     page_size=_BATCH_SIZE) or {}
            except (ApiError, AuthError, NetworkError):
                continue
            rows = [s for s in (d.get("scores") or [])
                    if (s.get("date") or "").startswith(day)]
            for s in rows[:_BATCH_SIZE]:
                eng = _ENGINE_MAP.get((s.get("platform") or "").strip().lower(),
                                      s.get("platform") or "")
                if not eng or eng == "kimi":
                    continue
                rec = {
                    "id": int(s.get("task_id") or 0) % 900000007,  # 前端安全 int id
                    "run_id": int(day.replace("-", "")),
                    "query_id": idmap.get(str(s.get("query_id") or ""), 0),
                    "engine": eng, "market": s.get("zone") or "",
                    "error": "",
                    "brand_mentioned": bool(s.get("exposure")),
                    "brand_rank": int(s.get("avg_rank")) if s.get("avg_rank") else None,
                    "competitors_mentioned": [], "cited_domains": [], "own_domain_cited": False,
                    "negative_cues": [], "needs_review": False, "answer": "",
                    "_ab_task_id": str(s.get("task_id") or ""),
                }
                samples.append(rec)
                day_samples.setdefault(day, []).append(rec)

        # 3) 竞品曲线：用 exposure/trends 的竞品当日提及率按比例标记当日样本
        try:
            rank = client.exposure_rank(begin_date=(_date.today() - _td(days=6)).isoformat(),
                                        end_date=_date.today().isoformat()) or []
            comp_ids = [str(r.get("competitor_id")) for r in rank
                        if str(r.get("competitor_id")) != "0"][:3]
            if comp_ids:
                tr = client.exposure_trends(
                    begin_date=(_date.today() - _td(days=6)).isoformat(),
                    end_date=_date.today().isoformat(), competitor_ids=comp_ids) or {}
                for c in tr.get("competitor_statistics") or []:
                    cname = c.get("name") or ""
                    if not cname:
                        continue
                    for st in c.get("statistics") or []:
                        d0 = (st.get("date") or "")[:10]
                        arr = day_samples.get(d0) or []
                        if not arr:
                            continue
                        r0 = float(st.get("exposure") or 0)
                        k = round(len(arr) * r0 / 100)
                        for rec in arr[:k]:
                            rec["competitors_mentioned"].append(cname)
        except (ApiError, AuthError, NetworkError):
            pass

        # 4) 批次（近 7 天有样本的采样日，倒序，截取 15）
        runs = []
        by_day: Dict[str, list] = {}
        for rec in samples:
            by_day.setdefault(str(rec["run_id"]), []).append(rec)
        for rid in sorted(by_day, reverse=True):
            day = f"{rid[:4]}-{rid[4:6]}-{rid[6:8]}"
            runs.append({"id": int(rid), "brand_id": 0, "status": "completed",
                         "total": len(by_day[rid]), "done": len(by_day[rid]),
                         "started_at": f"{day}T08:00:00", "finished_at": f"{day}T09:00:00"})
        runs = runs[:15]
        valid = {r["id"] for r in runs}
        samples = [s for s in samples if s["run_id"] in valid]

        data = {"queries": queries, "runs": runs, "samples": samples, "idmap": idmap}
        _compat_cache.update({"key": key, "ts": _time.time(), "data": data})
        return data


def _compat(db, part: str):
    """取兼容数据某部分；Answerbit 失败返回 None（调用方回退本地数据）。"""
    try:
        client = get_client(db)
        return _compat_build(client, _brand_name(db))[part]
    except (ConfigError, AuthError, ApiError, NetworkError):
        return None


def _compat_full(db):
    try:
        client = get_client(db)
        return _compat_build(client, _brand_name(db)), client
    except (ConfigError, AuthError, ApiError, NetworkError):
        return None, None


def ab_queries(db):
    return [{k: v for k, v in q.items() if not k.startswith("_")}
            for q in (_compat(db, "queries") or [])]


def ab_runs(db):
    return _compat(db, "runs")


def _ensure_answers(client: AnswerbitClient, rows: list, brand_domain: str = ""):
    """懒加载某批次样本的回答原文与引用域名（task_detail.llm_output/links），写回缓存。"""
    todo = [r for r in rows if r.get("_ab_task_id") and not r.get("answer")]
    if not todo:
        return
    dom = (brand_domain or "").lower()
    dom = dom[4:] if dom.startswith("www.") else dom
    for rec in todo:
        with _detail_sem:
            try:
                detail = client.task_detail(task_id=rec["_ab_task_id"]) or {}
                rec["answer"] = detail.get("llm_output") or ""
                # 引用域名（links 内 URL 的 host，去 www.）；含品牌官方域 → own_domain_cited
                domains = sorted({str(l.get("url") or "").split("/")[2].lower()
                                  for l in (detail.get("links") or [])
                                  if "://" in str(l.get("url") or "")})
                domains = [d[4:] if d.startswith("www.") else d for d in domains]
                if domains:
                    rec["cited_domains"] = domains
                    rec["own_domain_cited"] = bool(dom) and any(dom in d for d in domains)
            except (ApiError, AuthError, NetworkError):
                pass


def ab_samples(db, run_id, query_id=None):
    data, client = _compat_full(db)
    if data is None:
        return None
    rows = [s for s in data["samples"] if s["run_id"] == int(run_id)]
    if query_id is not None:
        rows = [s for s in rows if str(s["query_id"]) == str(query_id)]
    try:
        _ensure_answers(client, rows, _brand_domain(db))
    except Exception:
        pass
    return [{k: v for k, v in s.items() if not k.startswith("_")} for s in rows]


def ab_analysis(db, run_id):
    """与本地 /api/monitor/analysis 同形状：该批次（采样日）全部问题的真实指标行。

    指标来自平台 prompt_get_group（单日全量问题的提及率/平均排名），不依赖批次抽样样本——
    抽样仅覆盖少量问题，会导致选题库大部分行的洞察列与「回答记录」按钮缺失。
    """
    full, client = _compat_full(db)
    if full is None:
        return None
    brand_name = _brand_name(db)
    samples_all, idmap, queries = full["samples"], full["idmap"], full["queries"]
    rid = int(run_id)
    day = f"{rid // 10000}-{(rid // 100) % 100:02d}-{rid % 100:02d}"
    key = f"{client.brand_id}:{day}"
    with _compat_lock:
        cached = _analysis_cache.get(key)
        if not cached or _time.time() - cached["ts"] > 1800:
            rows = []
            page = 1
            while True:
                try:
                    group = client.prompt_get_group(begin_date=day, end_date=day,
                                                     page=page, page_size=50) or {}
                except (ApiError, AuthError, NetworkError):
                    break
                titles = group.get("titles") or []
                if not titles:
                    break
                for t in titles:
                    for q in t.get("prompts") or []:
                        qid = idmap.get(str(q.get("id") or ""))
                        if not qid:
                            continue
                        qstr = q.get("query_str") or ""
                        ss = [s for s in samples_all
                              if s["run_id"] == rid and s["query_id"] == qid]
                        rows.append({
                            "id": qid, "question": qstr,
                            "qgroup": q.get("title_name") or t.get("title_name") or "",
                            "market": "", "brand_in_question": bool(brand_name) and brand_name in qstr,
                            "tags": _wp_tags(qstr),
                            "samples": len(ss),
                            "mentioned": sum(1 for s in ss if s["brand_mentioned"]),
                            "mention_rate": round(float(q["exposure"]), 1) if q.get("exposure") is not None else None,
                            "avg_rank": round(float(q["avg_rank"]), 1) if q.get("avg_rank") else None,
                            "own_domain": False, "negative": False, "needs_review": False,
                            "delta": None,
                        })
                if int(group.get("total") or 0) <= page * 50:
                    break
                page += 1
            _analysis_cache[key] = {"ts": _time.time(), "rows": rows}
            cached = _analysis_cache[key]
    rows = cached["rows"]
    if not rows:
        return {"has_data": False}
    # 整体可见性（从批次抽样样本估算）
    vis = [s for s in samples_all if s["run_id"] == rid]
    vis_m = [s for s in vis if s["brand_mentioned"]]
    ranks_all = [s["brand_rank"] for s in vis_m if s["brand_rank"]]
    n = len(vis)
    overall = {
        "samples": n, "mentioned": len(vis_m),
        "mention_rate": round(100 * len(vis_m) / n) if n else None,
        "top1_rate": round(100 * sum(1 for r in ranks_all if r == 1) / n) if n else None,
        "top3_rate": round(100 * sum(1 for r in ranks_all if 1 <= r <= 3) / n) if n else None,
        "avg_rank": round(sum(ranks_all) / len(ranks_all), 2) if ranks_all else None,
    }
    return {"has_data": True, "queries": rows, "overall": overall,
            "engines": [], "citations": [], "competitors": []}


def ab_query_toggle(db, q_id: int):
    """启停监测 → 平台 prompt_update（status 1↔2）。"""
    data, client = _compat_full(db)
    if data is None:
        return None
    ab_id = next((k for k, v in data["idmap"].items() if v == int(q_id)), None)
    if not ab_id:
        return None
    cur = next((q for q in data["queries"] if q["id"] == int(q_id)), None)
    new_status = 2 if (cur and cur["active"]) else 1
    client.prompt_update(prompt_id=ab_id, status=new_status)
    return {"active": new_status == 1}


def ab_query_delete(db, q_id: int):
    """删除问题 → 平台 prompt_delete。"""
    data, client = _compat_full(db)
    if data is None:
        return None
    ab_id = next((k for k, v in data["idmap"].items() if v == int(q_id)), None)
    if not ab_id:
        return None
    client.prompt_delete(prompt_id=ab_id)
    return {"ok": True}
