"""Answerbit（腾讯 GEO 平台）OpenAPI 协议适配层。

协议要点（源自官方文档 https://answerbit.qq.com/zh-CN/docs/external/4-openapi-getting-started）：
- 鉴权：`X-API-Key` HTTP Header；
- Base URL 默认 `https://answerbit.qq.com`；
- 全部接口均为 POST，JSON 请求体；
- 统一响应 `{code, msg, data}`，`code=0` 表示成功；
- 64 位整数 ID 一律以十进制字符串传递；
- 生成/监控类接口为异步受理：create 返回受理成功，结果需轮询 get/status。

配置存储：settings 表 key=`answerbit_config`（JSON：api_key/base_url/team_id/brand_id），
环境变量 ANSWERBIT_API_KEY / ANSWERBIT_BASE_URL / ANSWERBIT_TEAM_ID / ANSWERBIT_BRAND_ID 兜底。

对参数签名已确认的接口提供具名方法；参数复杂或文档未完全展开的接口以 **payload 透传，
配合通用 `call()` 保证全部 OpenAPI 端点可用。
"""
from __future__ import annotations

import json
import os
import time
from typing import Any, Dict, List, Optional

import httpx

DEFAULT_BASE_URL = "https://answerbit.qq.com"
CONFIG_KEY = "answerbit_config"
_TIMEOUT = httpx.Timeout(20.0, connect=5.0)


# ---------- 错误体系 ----------

class AnswerbitError(Exception):
    """Answerbit 调用异常基类。"""


class ConfigError(AnswerbitError):
    """未配置 API Key 等配置类错误。"""


class AuthError(AnswerbitError):
    """鉴权失败（401/403，或 API Key 无效）。"""


class ApiError(AnswerbitError):
    """业务错误：code != 0 或 HTTP 非 2xx。"""

    def __init__(self, code: int, msg: str, status: int = 0):
        self.code = code
        self.msg = msg
        self.status = status
        super().__init__(f"[Answerbit] HTTP={status} code={code} msg={msg}")


class NetworkError(AnswerbitError):
    """网络/超时错误。"""


# ---------- 配置 ----------

def _env_config() -> Dict[str, str]:
    return {
        "api_key": os.environ.get("ANSWERBIT_API_KEY", ""),
        "base_url": os.environ.get("ANSWERBIT_BASE_URL", ""),
        "team_id": os.environ.get("ANSWERBIT_TEAM_ID", ""),
        "brand_id": os.environ.get("ANSWERBIT_BRAND_ID", ""),
    }


def load_config(db) -> Dict[str, str]:
    """合并环境变量与 DB 配置（DB 优先，env 仅填充空缺字段）。"""
    cfg = {"api_key": "", "base_url": "", "team_id": "", "brand_id": ""}
    env = _env_config()
    for k in cfg:
        if env[k]:
            cfg[k] = env[k]
    row = db.query(_setting_model(db)).filter_by(key=CONFIG_KEY).first()
    if row and row.value:
        try:
            stored = json.loads(row.value)
            if isinstance(stored, dict):
                for k in cfg:
                    if str(stored.get(k, "") or "").strip():
                        cfg[k] = str(stored[k]).strip()
        except json.JSONDecodeError:
            pass
    if not cfg["base_url"]:
        cfg["base_url"] = DEFAULT_BASE_URL
    return cfg


def save_config(db, patch: Dict[str, Any]) -> Dict[str, str]:
    """部分更新：值为空字符串/None 的字段保持原值（避免误清空 Key）。"""
    model = _setting_model(db)
    row = db.query(model).filter_by(key=CONFIG_KEY).first()
    stored: Dict[str, Any] = {}
    if row and row.value:
        try:
            stored = json.loads(row.value) or {}
        except json.JSONDecodeError:
            stored = {}
    for k in ("api_key", "base_url", "team_id", "brand_id"):
        v = patch.get(k)
        if v is None:
            continue
        v = str(v).strip()
        if v == "" and k != "base_url":  # 空串视为“不改”
            continue
        stored[k] = v
    if not stored.get("base_url"):
        stored["base_url"] = DEFAULT_BASE_URL
    if row:
        row.value = json.dumps(stored, ensure_ascii=False)
    else:
        db.add(model(key=CONFIG_KEY, value=json.dumps(stored, ensure_ascii=False)))
    db.commit()
    return load_config(db)


def mask_key(key: str) -> str:
    """Key 脱敏：仅保留前 4 位与后 4 位。"""
    if not key:
        return ""
    if len(key) <= 8:
        return "****"
    return f"{key[:4]}****{key[-4:]}"


def _setting_model(db):
    """延迟导入，避免与 api.py 循环依赖。"""
    from .models import Setting
    return Setting


# ---------- 客户端 ----------

class AnswerbitClient:
    """Answerbit OpenAPI 同步客户端（httpx），支持注入自定义 transport 便于测试。"""

    def __init__(self, api_key: str = "", base_url: str = "", team_id: str = "",
                 brand_id: str = "", transport: Optional[httpx.BaseTransport] = None):
        if not api_key:
            raise ConfigError("未配置 Answerbit API Key（设置页或环境变量 ANSWERBIT_API_KEY）")
        self.api_key = api_key
        self.base_url = (base_url or DEFAULT_BASE_URL).rstrip("/")
        self.team_id = team_id
        self.brand_id = brand_id
        self._transport = transport

    # ---- 基础 ----

    def _post(self, path: str, payload: Optional[dict] = None) -> Any:
        url = self.base_url + path
        headers = {"X-API-Key": self.api_key, "Content-Type": "application/json"}
        try:
            with httpx.Client(timeout=_TIMEOUT, transport=self._transport) as client:
                resp = client.post(url, json=payload or {}, headers=headers)
        except httpx.TimeoutException as e:
            raise NetworkError(f"[Answerbit] 请求超时：{path}") from e
        except httpx.TransportError as e:
            raise NetworkError(f"[Answerbit] 网络错误：{path} ({e})") from e
        if resp.status_code in (401, 403):
            try:
                reason = str((resp.json() or {}).get("msg", ""))
            except ValueError:
                reason = ""
            if resp.status_code == 401:
                raise AuthError(f"[Answerbit] 鉴权失败（401）：请检查 API Key{(' - ' + reason) if reason else ''}")
            raise AuthError(
                f"[Answerbit] 权限不足（403）：API Key 无该接口权限或套餐未开通{(' - ' + reason) if reason else ''}")
        if resp.status_code >= 500:
            raise ApiError(-1, f"服务端错误 HTTP {resp.status_code}", resp.status_code)
        try:
            body = resp.json()
        except ValueError:
            raise ApiError(-1, f"响应非 JSON（HTTP {resp.status_code}）", resp.status_code)
        if resp.status_code >= 400:
            raise ApiError(int(body.get("code", -1)), str(body.get("msg") or body),
                           resp.status_code)
        code = int(body.get("code", -1))
        if code != 0:
            raise ApiError(code, str(body.get("msg", "")), resp.status_code)
        return body.get("data")

    def call(self, path: str, payload: Optional[dict] = None) -> Any:
        """通用透传：path 以 `/geo` 开头（如 `/geo/article/get`）。"""
        if not path.startswith("/geo"):
            raise ApiError(-1, "path 必须以 /geo 开头")
        return self._post(path, payload)

    def _brand(self, brand_id: Optional[str]) -> str:
        """未显式传 brand_id 时使用配置中的默认品牌。"""
        bid = str(brand_id or "").strip() or self.brand_id
        if not bid:
            raise ConfigError("未指定 brand_id（请传入或在设置页配置默认品牌 ID）")
        return bid

    def _team(self, team_id: Optional[str]) -> str:
        tid = str(team_id or "").strip() or self.team_id
        if not tid:
            raise ConfigError("未指定 team_id（请传入或在设置页配置默认团队 ID）")
        return tid

    # ========== 概览页数据（监测中心） ==========

    def dashboard(self, brand_id: str = "", begin_date: str = "", end_date: str = "",
                  title_ids: Optional[List[str]] = None,
                  platforms: Optional[List[str]] = None,
                  tag_ids: Optional[List[str]] = None) -> Any:
        """顶部指标卡：提及率/平均排名/曝光效果分数（含 fluctuation）。"""
        return self._post("/geo/base/dashboard", {
            "brand_id": self._brand(brand_id), "begin_date": begin_date, "end_date": end_date,
            "title_ids": title_ids or [], "platforms": platforms or [], "tag_ids": tag_ids or [],
        })

    def prompt_trends(self, brand_id: str = "", begin_date: str = "", end_date: str = "",
                     title_ids: Optional[List[str]] = None,
                     tag_ids: Optional[List[str]] = None) -> Any:
        return self._post("/geo/prompt/trends", {
            "brand_id": self._brand(brand_id), "begin_date": begin_date, "end_date": end_date,
            "title_ids": title_ids or [], "tag_ids": tag_ids or [],
        })

    def exposure_trends(self, brand_id: str = "", begin_date: str = "", end_date: str = "",
                        title_ids: Optional[List[str]] = None,
                        competitor_ids: Optional[List[str]] = None,
                        platforms: Optional[List[str]] = None,
                        tag_ids: Optional[List[str]] = None) -> Any:
        """提及率/平均排名按日趋势（趋势曲线，可带竞品同期曲线）。"""
        return self._post("/geo/exposure/trends", {
            "brand_id": self._brand(brand_id), "begin_date": begin_date, "end_date": end_date,
            "title_ids": title_ids or [], "competitor_ids": competitor_ids or [],
            "platforms": platforms or [], "tag_ids": tag_ids or [],
        })

    def score_trends(self, brand_id: str = "", begin_date: str = "", end_date: str = "",
                     title_ids: Optional[List[str]] = None,
                     competitor_ids: Optional[List[str]] = None,
                     platforms: Optional[List[str]] = None,
                     tag_ids: Optional[List[str]] = None) -> Any:
        return self._post("/geo/score/trends", {
            "brand_id": self._brand(brand_id), "begin_date": begin_date, "end_date": end_date,
            "title_ids": title_ids or [], "competitor_ids": competitor_ids or [],
            "platforms": platforms or [], "tag_ids": tag_ids or [],
        })

    def exposure_rank(self, brand_id: str = "", begin_date: str = "", end_date: str = "",
                      title_ids: Optional[List[str]] = None,
                      competitor_ids: Optional[List[str]] = None,
                      platforms: Optional[List[str]] = None,
                      tag_ids: Optional[List[str]] = None) -> Any:
        """品牌与竞品提及率/排名对比（competitor_id=0 为本品牌）。"""
        return self._post("/geo/exposure/rank", {
            "brand_id": self._brand(brand_id), "begin_date": begin_date, "end_date": end_date,
            "title_ids": title_ids or [], "competitor_ids": competitor_ids or [],
            "platforms": platforms or [], "tag_ids": tag_ids or [],
        })

    def score_rank(self, brand_id: str = "", begin_date: str = "", end_date: str = "",
                   title_ids: Optional[List[str]] = None,
                   competitor_ids: Optional[List[str]] = None,
                   platforms: Optional[List[str]] = None,
                   tag_ids: Optional[List[str]] = None) -> Any:
        return self._post("/geo/score/rank", {
            "brand_id": self._brand(brand_id), "begin_date": begin_date, "end_date": end_date,
            "title_ids": title_ids or [], "competitor_ids": competitor_ids or [],
            "platforms": platforms or [], "tag_ids": tag_ids or [],
        })

    def title_rank(self, brand_id: str = "", begin_date: str = "", end_date: str = "",
                   title_ids: Optional[List[str]] = None,
                   platforms: Optional[List[str]] = None,
                   tag_ids: Optional[List[str]] = None) -> Any:
        """按提问分类分组的提及率/排名/分数。"""
        return self._post("/geo/title/rank", {
            "brand_id": self._brand(brand_id), "begin_date": begin_date, "end_date": end_date,
            "title_ids": title_ids or [], "platforms": platforms or [], "tag_ids": tag_ids or [],
        })

    def domain_rank(self, brand_id: str = "", begin_date: str = "", end_date: str = "",
                    title_ids: Optional[List[str]] = None,
                    prompt_ids: Optional[List[str]] = None,
                    platforms: Optional[List[str]] = None,
                    tag_ids: Optional[List[str]] = None,
                    domain: str = "", page: int = 1, page_size: int = 10) -> Any:
        return self._post("/geo/domain/rank", {
            "brand_id": self._brand(brand_id), "begin_date": begin_date, "end_date": end_date,
            "title_ids": title_ids or [], "prompt_ids": prompt_ids or [],
            "platforms": platforms or [], "tag_ids": tag_ids or [],
            "domain": domain, "page": page, "page_size": page_size,
        })

    def article_rank(self, brand_id: str = "", begin_date: str = "", end_date: str = "",
                     title_ids: Optional[List[str]] = None,
                     prompt_ids: Optional[List[str]] = None,
                     platforms: Optional[List[str]] = None,
                     tag_ids: Optional[List[str]] = None,
                     keyword: str = "", page: int = 1, page_size: int = 10) -> Any:
        return self._post("/geo/article/rank", {
            "brand_id": self._brand(brand_id), "begin_date": begin_date, "end_date": end_date,
            "title_ids": title_ids or [], "prompt_ids": prompt_ids or [],
            "platforms": platforms or [], "tag_ids": tag_ids or [],
            "keyword": keyword, "page": page, "page_size": page_size,
        })

    def filter_platforms(self, team_id: str = "") -> Any:
        """可筛选的大模型平台（key=展示名，value=平台标识）。"""
        return self._post("/geo/team/get/filter_platforms", {"team_id": self._team(team_id)})

    # ========== 大模型回答（回答记录） ==========

    def task_list(self, brand_id: str = "", begin_date: str = "", end_date: str = "",
                  include: Optional[int] = None, prompt: str = "",
                  title_ids: Optional[List[str]] = None, prompt_ids: Optional[List[str]] = None,
                  tag_ids: Optional[List[str]] = None, task_ids: Optional[List[str]] = None,
                  platforms: Optional[List[str]] = None, language: Optional[List[str]] = None,
                  mention_brand: int = -1, min_score: Optional[int] = None,
                  max_score: Optional[int] = None, include_unanalyzed: bool = False,
                  url: str = "", ref_platform: str = "", article_id: str = "",
                  page: int = 1, page_size: int = 20) -> Any:
        """回答记录列表（scores 数组 + total）。"""
        payload: Dict[str, Any] = {
            "brand_id": self._brand(brand_id), "begin_date": begin_date, "end_date": end_date,
            "platforms": platforms or [], "language": language or [],
            "mention_brand": mention_brand, "include_unanalyzed": include_unanalyzed,
            "page": page, "page_size": page_size,
        }
        for k, v in (("include", include), ("prompt", prompt), ("title_ids", title_ids),
                     ("prompt_ids", prompt_ids), ("tag_ids", tag_ids), ("task_ids", task_ids),
                     ("min_score", min_score), ("max_score", max_score),
                     ("url", url), ("ref_platform", ref_platform), ("article_id", article_id)):
            if v not in (None, "", []):
                payload[k] = v
        return self._post("/geo/task/get", payload)

    def task_detail(self, brand_id: str = "", task_id: str = "") -> Any:
        """回答详情：llm_output 原文、links 引用、pic、recommend_queries、video/product_cards。"""
        if not task_id:
            raise ApiError(-1, "task_id 不能为空")
        return self._post("/geo/task/detail/get", {
            "brand_id": self._brand(brand_id), "task_id": task_id,
        })

    def prompt_run(self, brand_id: str = "", prompt_ids: Optional[List[str]] = None,
                   run_count: int = 1, platforms: Optional[List[str]] = None) -> Any:
        """手动运行监控提问（异步受理；20 积分/任务，谨慎调用）。"""
        if not prompt_ids:
            raise ApiError(-1, "prompt_ids 不能为空")
        return self._post("/geo/prompt/run", {
            "brand_id": self._brand(brand_id), "prompt_ids": prompt_ids,
            "run_count": run_count, "platforms": platforms or [],
        })

    # ========== 推荐提问（选题库） ==========

    def recommendation_trigger(self, brand_id: str = "", target_date: str = "") -> Any:
        """异步生成推荐选题；结果用 recommendation_list 轮询。"""
        payload: Dict[str, Any] = {"brand_id": self._brand(brand_id)}
        if target_date:
            payload["target_date"] = target_date
        return self._post("/geo/question-recommendation/trigger", payload)

    def recommendation_list(self, brand_id: str = "", question_type: int = 0,
                            intent_type: int = 0, status: str = "", sort_by: str = "",
                            sort_order: str = "", min_heat_score: Optional[float] = None,
                            date_from: str = "", date_to: str = "",
                            page: int = 1, page_size: int = 20) -> Any:
        """推荐选题列表（PENDING/CONFIRMED/EDITED；heat_score 热度分）。"""
        payload: Dict[str, Any] = {
            "brand_id": self._brand(brand_id), "question_type": question_type,
            "page": page, "page_size": page_size,
        }
        for k, v in (("intent_type", intent_type if intent_type else None),
                     ("status", status), ("sort_by", sort_by), ("sort_order", sort_order),
                     ("min_heat_score", min_heat_score), ("date_from", date_from),
                     ("date_to", date_to)):
            if v not in (None, "", 0):
                payload[k] = v
        return self._post("/geo/question-recommendation/list", payload)

    def recommendation_confirm(self, recommendation_id: str) -> Any:
        """确认推荐选题 → 自动创建监控提问，返回 monitor_query_id。"""
        if not recommendation_id:
            raise ApiError(-1, "recommendation_id 不能为空")
        return self._post("/geo/question-recommendation/confirm", {"recommendation_id": recommendation_id})

    # ========== 用户提问与分类 ==========

    def prompt_get(self, brand_id: str = "", prompt_ids: Optional[List[str]] = None,
                   page: int = 1, page_size: int = 20, query_str: str = "",
                   title_ids: Optional[List[str]] = None, status: Optional[int] = None,
                   tag_ids: Optional[List[str]] = None,
                   models: Optional[List[str]] = None) -> Any:
        payload: Dict[str, Any] = {"brand_id": self._brand(brand_id), "page": page, "page_size": page_size}
        for k, v in (("prompt_ids", prompt_ids), ("query_str", query_str),
                     ("title_ids", title_ids), ("status", status), ("tag_ids", tag_ids),
                     ("models", models)):
            if v not in (None, "", []):
                payload[k] = v
        return self._post("/geo/api/prompt/get", payload)

    def prompt_create(self, brand_id: str = "", title_id: str = "", query_str: str = "",
                      recommend_id: str = "", status: int = 1,
                      run_immediately: bool = False) -> Any:
        if not (title_id and query_str):
            raise ApiError(-1, "title_id 与 query_str 必填")
        payload: Dict[str, Any] = {
            "brand_id": self._brand(brand_id), "title_id": title_id, "query_str": query_str,
            "status": status, "run_immediately": run_immediately,
        }
        if recommend_id:
            payload["recommend_id"] = recommend_id
        return self._post("/geo/prompt/create", payload)

    def prompt_create_batch(self, brand_id: str = "", title_id: str = "",
                            prompts: Optional[List[str]] = None,
                            recommend_ids: Optional[List[str]] = None, status: int = 1,
                            run_immediately: bool = False) -> Any:
        if not (title_id and prompts):
            raise ApiError(-1, "title_id 与 prompts 必填")
        payload: Dict[str, Any] = {
            "brand_id": self._brand(brand_id), "title_id": title_id, "prompts": prompts,
            "status": status, "run_immediately": run_immediately,
        }
        if recommend_ids:
            payload["recommend_ids"] = recommend_ids
        return self._post("/geo/prompt/create/batch", payload)

    def prompt_update(self, brand_id: str = "", prompt_id: str = "", query_str: str = "",
                      status: Optional[int] = None) -> Any:
        """局部更新（patch 语义）：query_str 不能更新为空串；status=0 表示不更新。"""
        if not prompt_id:
            raise ApiError(-1, "prompt_id 必填")
        payload: Dict[str, Any] = {"id": prompt_id, "brand_id": self._brand(brand_id)}
        if query_str:
            payload["query_str"] = query_str
        if status is not None:
            payload["status"] = status
        return self._post("/geo/prompt/update", payload)

    def prompt_delete(self, brand_id: str = "", prompt_id: str = "") -> Any:
        return self._post("/geo/prompt/delete", {
            "id": prompt_id, "brand_id": self._brand(brand_id)})

    def prompt_delete_batch(self, brand_id: str = "", prompt_ids: Optional[List[str]] = None) -> Any:
        return self._post("/geo/prompt/delete/batch", {
            "brand_id": self._brand(brand_id), "prompt_ids": prompt_ids or []})

    def prompt_get_group(self, brand_id: str = "", group_type: int = 1,
                         begin_date: str = "", end_date: str = "",
                         title_ids: Optional[List[str]] = None, tag_ids: Optional[List[str]] = None,
                         query_str: str = "", page: int = 1, page_size: int = 20) -> Any:
        """按分类分组的提问视图（含曝光率/排名/每日均分）。日期需成对传。"""
        payload: Dict[str, Any] = {
            "brand_id": self._brand(brand_id), "group_type": group_type,
            "page": page, "page_size": page_size,
        }
        if begin_date and end_date:
            payload["begin_date"], payload["end_date"] = begin_date, end_date
        for k, v in (("title_ids", title_ids), ("tag_ids", tag_ids), ("query_str", query_str)):
            if v not in (None, "", []):
                payload[k] = v
        return self._post("/geo/prompt/get/group", payload)

    def prompt_relation_update(self, brand_id: str = "", title_id: str = "",
                               prompt_id: str = "") -> Any:
        """把提问重新归类（替换语义）。"""
        return self._post("/geo/prompt/relation/update", {
            "brand_id": self._brand(brand_id), "title_id": title_id, "prompt_id": prompt_id})

    def title_get(self, brand_id: str = "", title_name: str = "", title_id: str = "") -> Any:
        payload: Dict[str, Any] = {"brand_id": self._brand(brand_id)}
        if title_id:
            payload["id"] = title_id
        if title_name:
            payload["title_name"] = title_name
        return self._post("/geo/title/get", payload)

    def title_create(self, brand_id: str = "", title_name: str = "",
                     title_desc: str = "") -> Any:
        return self._post("/geo/title/create", {
            "brand_id": self._brand(brand_id), "title_name": title_name, "title_desc": title_desc})

    def title_update(self, brand_id: str = "", title_id: str = "", title_name: str = "",
                     title_desc: Optional[str] = None) -> Any:
        payload: Dict[str, Any] = {
            "id": title_id, "brand_id": self._brand(brand_id), "title_name": title_name}
        if title_desc is not None:
            payload["title_desc"] = title_desc
        return self._post("/geo/title/update", payload)

    def title_delete(self, title_id: str = "") -> Any:
        return self._post("/geo/title/delete", {"id": title_id})

    # ---- 提问标签 / 模型绑定 ----

    def prompt_tag_create(self, team_id: str = "", tag_names: Optional[List[str]] = None) -> Any:
        return self._post("/geo/api/prompt/tag/create", {
            "team_id": self._team(team_id), "tag_names": tag_names or []})

    def prompt_tag_update(self, team_id: str = "", tag_id: str = "", tag_name: str = "") -> Any:
        return self._post("/geo/api/prompt/tag/update", {
            "team_id": self._team(team_id), "tag_id": tag_id, "tag_name": tag_name})

    def prompt_tag_get(self, team_id: str = "", tag_type: Optional[List[int]] = None) -> Any:
        """团队标签：tag_type=[3] 查询模型标签；不传查用户标签。"""
        payload: Dict[str, Any] = {"team_id": self._team(team_id)}
        if tag_type:
            payload["tag_type"] = tag_type
        return self._post("/geo/prompt/tag/get", payload)

    def prompt_tag_delete(self, team_id: str = "", tag_ids: Optional[List[str]] = None) -> Any:
        return self._post("/geo/api/prompt/tag/delete", {
            "team_id": self._team(team_id), "tag_ids": tag_ids or []})

    def prompt_tag_relation_get(self, brand_id: str = "", prompt_id: str = "") -> Any:
        return self._post("/geo/api/prompt/tag/relation/get", {
            "brand_id": self._brand(brand_id), "prompt_id": prompt_id})

    def prompt_tag_relation_batch(self, brand_id: str = "",
                                 prompt_ids: Optional[List[str]] = None) -> Any:
        return self._post("/geo/api/prompt/tag/relation/batch", {
            "brand_id": self._brand(brand_id), "prompt_ids": prompt_ids or []})

    def prompt_tag_relation_add(self, brand_id: str = "", prompt_id: str = "",
                                tag_ids: Optional[List[str]] = None) -> Any:
        return self._post("/geo/api/prompt/tag/relation/add", {
            "brand_id": self._brand(brand_id), "prompt_id": prompt_id, "tag_ids": tag_ids or []})

    def prompt_tag_relation_remove(self, brand_id: str = "", prompt_id: str = "",
                                   tag_ids: Optional[List[str]] = None) -> Any:
        return self._post("/geo/api/prompt/tag/relation/remove", {
            "brand_id": self._brand(brand_id), "prompt_id": prompt_id, "tag_ids": tag_ids or []})

    def prompt_tag_relation_add_batch(self, brand_id: str = "",
                                      prompt_ids: Optional[List[str]] = None,
                                      tag_ids: Optional[List[str]] = None) -> Any:
        return self._post("/geo/api/prompt/tag/relation/add/batch", {
            "brand_id": self._brand(brand_id), "prompt_ids": prompt_ids or [], "tag_ids": tag_ids or []})

    def prompt_tag_relation_remove_batch(self, brand_id: str = "",
                                         prompt_ids: Optional[List[str]] = None,
                                         tag_ids: Optional[List[str]] = None) -> Any:
        return self._post("/geo/api/prompt/tag/relation/remove/batch", {
            "brand_id": self._brand(brand_id), "prompt_ids": prompt_ids or [], "tag_ids": tag_ids or []})

    def model_relation_replace(self, team_id: str = "",
                               prompt_ids: Optional[List[str]] = None,
                               tag_ids: Optional[List[str]] = None) -> Any:
        """全量替换提问的模型标签（[] 清空绑定）。"""
        return self._post("/geo/prompt/tag/relation/model/replace", {
            "team_id": self._team(team_id), "prompt_ids": prompt_ids or [], "tag_ids": tag_ids or []})

    def model_relation_batch(self, team_id: str = "",
                             prompt_ids: Optional[List[str]] = None,
                             tag_type: Optional[List[int]] = None) -> Any:
        """读回提问的模型绑定（tag_type=[3]）。"""
        payload: Dict[str, Any] = {"team_id": self._team(team_id), "prompt_ids": prompt_ids or []}
        if tag_type:
            payload["tag_type"] = tag_type
        return self._post("/geo/prompt/tag/relation/batch", payload)

    # ========== 文章/内容管理（内容工厂） ==========

    def article_template_get(self, brand_id: str = "", **extra) -> Any:
        """可用文章模板列表（生成前建议先调用）。"""
        payload = {"brand_id": self._brand(brand_id)}
        payload.update(extra)
        return self._post("/geo/article/template/get", payload)

    def article_create(self, brand_id: str = "", template_type: str = "",
                       prompt_ids: Optional[List[str]] = None,
                       knowledge_ids: Optional[List[str]] = None,
                       high_ref: Optional[Dict[str, Any]] = None,
                       tag_ids: Optional[List[str]] = None, language: str = "",
                       **extra) -> Any:
        """提交文章生成任务（异步受理，≤prompt_ids 20 / knowledge_ids 20）。

        high_ref：仿写范文 {"url": ...} 或 {"title": ..., "content": ...}。
        """
        payload: Dict[str, Any] = {
            "brand_id": self._brand(brand_id), "template_type": template_type,
            "prompt_ids": prompt_ids or [], "knowledge_ids": knowledge_ids or [],
            "tag_ids": tag_ids or [],
        }
        if high_ref:
            payload["high_ref"] = high_ref
        if language:
            payload["language"] = language
        payload.update(extra)
        return self._post("/geo/article/create", payload)

    def article_get(self, brand_id: str = "", article_id: str = "") -> Any:
        """单篇文章标题/正文/状态（status: 0生成中/1待发布/2发布中/3追踪中/4失败）。

        注意：经真实 API 实测，查询参数为 `article_id`（update 接口才是 `id`）。
        """
        if not article_id:
            raise ApiError(-1, "article_id 必填")
        return self._post("/geo/article/get", {
            "brand_id": self._brand(brand_id), "article_id": article_id})

    def article_query(self, brand_id: str = "", **extra) -> Any:
        """文章列表 + 文章维度引用汇总（游标分页，参数透传）。"""
        payload = {"brand_id": self._brand(brand_id)}
        payload.update(extra)
        return self._post("/geo/article/query", payload)

    def article_upload(self, brand_id: str = "", **payload) -> Any:
        """保存粘贴正文/本地上传的文章（JSON 提交，不收原始文件；字段透传）。"""
        payload.setdefault("brand_id", self._brand(brand_id))
        return self._post("/geo/article/upload", payload)

    def article_update(self, brand_id: str = "", article_id: str = "",
                       title: str = "", main_body: str = "", language: str = "") -> Any:
        """编辑文章。注意：main_body 为全量替换，省略会被置空；仅 status>=1 可编辑。"""
        if not (article_id and title):
            raise ApiError(-1, "article_id 与 title 必填")
        payload: Dict[str, Any] = {
            "brand_id": self._brand(brand_id), "id": article_id, "title": title}
        if main_body:
            payload["main_body"] = main_body
        if language:
            payload["language"] = language
        return self._post("/geo/article/update", payload)

    def article_tag_get(self, **payload) -> Any:
        return self._post("/geo/article/tag/get", payload)

    def article_tag_create(self, **payload) -> Any:
        return self._post("/geo/article/tag/create", payload)

    def article_tag_update(self, **payload) -> Any:
        return self._post("/geo/article/tag/update", payload)

    def article_tag_delete(self, **payload) -> Any:
        return self._post("/geo/article/tag/delete", payload)

    # ---- 引用追踪 ----

    def trace_save(self, brand_id: str = "", **payload) -> Any:
        """新建文章并加入引用追踪（字段透传）。"""
        payload.setdefault("brand_id", self._brand(brand_id))
        return self._post("/geo/article/trace/save", payload)

    def trace_detail(self, brand_id: str = "", **payload) -> Any:
        """单篇文章追踪详情（按 AI 平台拆分的引用明细）。"""
        payload.setdefault("brand_id", self._brand(brand_id))
        return self._post("/geo/article/trace/detail", payload)

    # ---- 发布 ----

    def distribute(self, brand_id: str = "", **payload) -> Any:
        """提交文章自动发布（字段透传）。"""
        payload.setdefault("brand_id", self._brand(brand_id))
        return self._post("/geo/article/distribute", payload)

    def distribute_selected(self, brand_id: str = "", **payload) -> Any:
        """发布选定的视频/图文素材（仅 douyin）。"""
        payload.setdefault("brand_id", self._brand(brand_id))
        return self._post("/geo/article/distribute/selected", payload)

    def distribute_records(self, brand_id: str = "", **payload) -> Any:
        """查询自动发布记录（publish_status: 1发布中/2成功/3失败；游标分页）。"""
        payload.setdefault("brand_id", self._brand(brand_id))
        return self._post("/geo/article/distribute/list/records", payload)

    def distribute_unbind(self, brand_id: str = "", **payload) -> Any:
        """解除文章与发布链接的关联（不删外部平台内容）。"""
        payload.setdefault("brand_id", self._brand(brand_id))
        return self._post("/geo/article/distribute/unbind", payload)

    # ---- 视频/图文任务 ----

    def video_create(self, brand_id: str = "", **payload) -> Any:
        payload.setdefault("brand_id", self._brand(brand_id))
        return self._post("/geo/video/create", payload)

    def video_status(self, brand_id: str = "", **payload) -> Any:
        payload.setdefault("brand_id", self._brand(brand_id))
        return self._post("/geo/video/status", payload)

    def video_list(self, brand_id: str = "", **payload) -> Any:
        payload.setdefault("brand_id", self._brand(brand_id))
        return self._post("/geo/video/list", payload)

    def video_delete(self, brand_id: str = "", **payload) -> Any:
        """删除任务记录（不取消进行中的任务）。"""
        payload.setdefault("brand_id", self._brand(brand_id))
        return self._post("/geo/video/delete", payload)

    def image_text_download_pack(self, brand_id: str = "", **payload) -> Any:
        payload.setdefault("brand_id", self._brand(brand_id))
        return self._post("/geo/video/image-text/download-pack", payload)

    def wait_article(self, brand_id: str = "", article_id: str = "",
                     timeout: float = 300.0, interval: float = 5.0) -> Dict[str, Any]:
        """轮询生成任务直至离开“生成中”（status 0），返回最新文章数据。"""
        deadline = time.time() + timeout
        last: Dict[str, Any] = {}
        while True:
            last = self.article_get(brand_id=brand_id, article_id=article_id) or {}
            status = int(last.get("status", 0) or 0)
            if status != 0 or time.time() + interval > deadline:
                return {"status": status, "article": last}
            time.sleep(interval)

    # ========== 品牌 / 竞品 / 团队 ==========

    def brand_list(self, team_id: str = "") -> Any:
        return self._post("/geo/query/brand", {"team_id": self._team(team_id)})

    def brand_create(self, team_id: str = "", brand: str = "", alias: str = "",
                     website: str = "", description: str = "", note: str = "",
                     icon_mime_type: str = "", icon_data: str = "") -> Any:
        payload: Dict[str, Any] = {"team_id": self._team(team_id), "brand": brand}
        for k, v in (("alias", alias), ("website", website), ("description", description),
                     ("note", note), ("icon_mime_type", icon_mime_type), ("icon_data", icon_data)):
            if v:
                payload[k] = v
        return self._post("/geo/brand/create", payload)

    def brand_bundle_create(self, team_id: Optional[str] = None, team: Optional[dict] = None,
                            brand: Optional[dict] = None,
                            user_prompts: Optional[List[dict]] = None,
                            competitors: Optional[List[dict]] = None) -> Any:
        """捆绑初始化：团队+品牌+竞品+提问一次建齐。"""
        payload: Dict[str, Any] = {"brand": brand, "user_prompts": user_prompts or []}
        if team_id:
            payload["team_id"] = team_id
        if team:
            payload["team"] = team
        if competitors:
            payload["competitors"] = competitors
        return self._post("/geo/brand/bundle/create", payload)

    def brand_update(self, brand_id: str = "", **payload) -> Any:
        """编辑品牌基础信息（全量传参，未传字段可能被置空）。"""
        payload.setdefault("id", brand_id or self.brand_id)
        return self._post("/geo/brand/update", payload)

    def brand_update_icon(self, brand_id: str = "", mime_type: str = "",
                          data: str = "") -> Any:
        return self._post("/geo/brand/update/icon", {
            "brand_id": self._brand(brand_id), "mime_type": mime_type, "data": data})

    def competitor_get(self, brand_id: str = "") -> Any:
        return self._post("/geo/competitor/get", {"brand_id": self._brand(brand_id)})

    def competitor_create(self, brand_id: str = "", competitor_name: str = "",
                          competitor_alias: str = "") -> Any:
        return self._post("/geo/competitor/create", {
            "brand_id": self._brand(brand_id), "competitor_name": competitor_name,
            "competitor_alias": competitor_alias})

    def competitor_update(self, brand_id: str = "", competitor_id: str = "",
                          competitor_name: str = "", competitor_alias: str = "") -> Any:
        """全量传参，未传字段可能被置空。"""
        return self._post("/geo/competitor/update", {
            "brand_id": self._brand(brand_id), "competitor_id": competitor_id,
            "competitor_name": competitor_name, "competitor_alias": competitor_alias})

    def competitor_delete(self, brand_id: str = "", competitor_id: str = "") -> Any:
        return self._post("/geo/competitor/delete", {
            "brand_id": self._brand(brand_id), "competitor_id": competitor_id})

    def team_logs(self, team_id: str = "", page: int = 1, page_size: int = 20,
                  actions: Optional[List[str]] = None,
                  operator_uids: Optional[List[str]] = None) -> Any:
        payload: Dict[str, Any] = {"team_id": self._team(team_id), "page": page, "page_size": page_size}
        if actions:
            payload["actions"] = actions
        if operator_uids:
            payload["operator_uids"] = operator_uids
        return self._post("/geo/team/logs", payload)

    # ========== 监控配置 ==========

    def team_config_get(self, team_id: str = "", include_disabled: bool = False) -> Any:
        return self._post("/geo/team/config", {
            "team_id": self._team(team_id), "include_disabled": include_disabled})

    def brand_config_get(self, brand_id: str = "", include_disabled: bool = False) -> Any:
        return self._post("/geo/brand/config", {
            "brand_id": self._brand(brand_id), "include_disabled": include_disabled})

    def team_config_update(self, team_id: str = "",
                           models: Optional[List[dict]] = None) -> Any:
        """保存团队监控配置（仅更新已开通模型的 PC frequency）。"""
        return self._post("/geo/team/config/models/update", {
            "team_id": self._team(team_id), "models": models or []})

    def brand_config_update(self, brand_id: str = "",
                            models: Optional[List[dict]] = None) -> Any:
        """保存品牌监控配置（PC/手机独立；手机需 mobile_unlocked）。"""
        return self._post("/geo/brand/config/models/update", {
            "brand_id": self._brand(brand_id), "models": models or []})

    def brand_config_reset(self, brand_id: str = "") -> Any:
        """删除品牌自有配置，恢复跟随团队默认。"""
        return self._post("/geo/brand/config/delete", {"brand_id": self._brand(brand_id)})

    # ========== 素材库（知识库） ==========

    def material_query(self, brand_id: str = "", parent_id: str = "", title: str = "",
                       tags: Optional[List[str]] = None, limit: int = 20,
                       scroll_id: str = "") -> Any:
        payload: Dict[str, Any] = {"brand_id": self._brand(brand_id), "limit": limit}
        if parent_id:
            payload["parent_id"] = parent_id
        if title:
            payload["title"] = title
        if tags:
            payload["tags"] = tags
        if scroll_id:
            payload["scroll_id"] = scroll_id
        return self._post("/geo/material/query", payload)

    def material_get(self, brand_id: str = "", material_id: str = "") -> Any:
        return self._post("/geo/material/get", {
            "brand_id": self._brand(brand_id), "material_id": material_id})

    def material_upload_presign(self, brand_id: str = "", file_name: str = "",
                               file_size: int = 0) -> Any:
        """预签名直传（5 分钟有效，PUT 无需 API Key；取得地址不会自动创建素材）。"""
        return self._post("/geo/material/upload/presign", {
            "brand_id": self._brand(brand_id), "file_name": file_name, "file_size": file_size})

    def material_update(self, brand_id: str = "", material_id: str = "", title: str = "",
                        tags: Optional[List[str]] = None) -> Any:
        """更新素材标题/标签；tags 为全量列表（空=清空）。"""
        payload: Dict[str, Any] = {
            "brand_id": self._brand(brand_id), "id": material_id, "title": title}
        if tags is not None:
            payload["tags"] = tags
        return self._post("/geo/material/update", payload)

    def material_move(self, brand_id: str = "", target_parent_id: str = "",
                      material_ids: Optional[List[str]] = None) -> Any:
        return self._post("/geo/material/move", {
            "brand_id": self._brand(brand_id), "target_parent_id": target_parent_id,
            "material_ids": material_ids or []})

    def material_delete(self, brand_id: str = "", material_id: str = "") -> Any:
        return self._post("/geo/material/delete", {
            "brand_id": self._brand(brand_id), "id": material_id})

    def material_download_presign(self, brand_id: str = "", material_id: str = "") -> Any:
        return self._post("/geo/material/download/presign", {
            "brand_id": self._brand(brand_id), "material_id": material_id})

    # ========== 商品卡（电商增强） ==========

    def shop_dashboard_base(self, brand_id: str = "", begin_date: str = "",
                           end_date: str = "", **extra) -> Any:
        """商品看板：触发/提及/平均排名/推荐份额。"""
        payload = {"brand_id": self._brand(brand_id), "begin_date": begin_date, "end_date": end_date}
        payload.update(extra)
        return self._post("/geo/api/shop/dashboard/base", payload)

    def shop_list(self, brand_id: str = "", **payload) -> Any:
        payload.setdefault("brand_id", self._brand(brand_id))
        return self._post("/geo/api/shop/list", payload)

    def shop_get(self, brand_id: str = "", shop_id: str = "") -> Any:
        return self._post("/geo/api/shop/get", {
            "brand_id": self._brand(brand_id), "shop_id": shop_id})

    def product_list(self, brand_id: str = "", **payload) -> Any:
        payload.setdefault("brand_id", self._brand(brand_id))
        return self._post("/geo/api/product/list", payload)


# ---------- 便捷构造 ----------

def get_client(db, transport: Optional[httpx.BaseTransport] = None) -> AnswerbitClient:
    """从 DB 配置构造客户端；未配置 API Key 时抛 ConfigError。"""
    cfg = load_config(db)
    return AnswerbitClient(
        api_key=cfg["api_key"], base_url=cfg["base_url"],
        team_id=cfg["team_id"], brand_id=cfg["brand_id"], transport=transport)
