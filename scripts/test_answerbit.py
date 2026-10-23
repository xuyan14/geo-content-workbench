"""Answerbit 协议适配层冒烟测试（无需真实 API Key，MockTransport 拦截请求）。

运行：cd geo-workbench && python3 scripts/test_answerbit.py
"""
import sys
import json
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import httpx  # noqa: E402

from app.answerbit import (  # noqa: E402
    AnswerbitClient, ApiError, AuthError, ConfigError, NetworkError, mask_key,
)

PASS = 0
FAIL = 0


def ok(name):
    global PASS
    PASS += 1
    print(f"  PASS  {name}")


def fail(name, err):
    global FAIL
    FAIL += 1
    print(f"  FAIL  {name}: {err}")


def check(name, fn):
    try:
        fn()
        ok(name)
    except Exception as e:  # noqa: BLE001
        fail(name, e)


# ---------- mock 服务端：记录请求并返回预设响应 ----------

REQUESTS: list[dict] = []


def handler(request: httpx.Request) -> httpx.Response:
    REQUESTS.append({
        "path": request.url.path,
        "api_key": request.headers.get("X-API-Key"),
        "body": json.loads(request.content or b"{}"),
    })
    path = request.url.path
    if path == "/geo/auth/401":
        return httpx.Response(401, json={"code": 1001, "msg": "invalid api key", "data": None})
    if path == "/geo/biz/error":
        return httpx.Response(200, json={"code": 500, "msg": "参数错误", "data": None})
    if path == "/geo/api/prompt/get":
        return httpx.Response(200, json={"code": 0, "msg": "success",
                                         "data": {"prompts": [{"prompt_id": "p1"}], "total": 1}})
    if path == "/geo/article/get":
        body = json.loads(request.content)
        calls = [r for r in REQUESTS if r["path"] == path]
        # 第 1 次生成中(0)，第 2 次完成(1) —— 用于 wait_article 轮询
        status = 0 if len(calls) == 1 else 1
        return httpx.Response(200, json={"code": 0, "msg": "success", "data": {
            "id": body.get("id"), "title": "T", "main_body": "B", "status": status}})
    if path == "/geo/team/get/filter_platforms":
        return httpx.Response(200, json={"code": 0, "msg": "success",
                                         "data": {"DEEPSEEK": "deepseek", "DOUBAO": "doubao"}})
    if path == "/geo/base/dashboard":
        body = json.loads(request.content)
        assert body["begin_date"] and body["end_date"], "dashboard 必须成对传日期"
        return httpx.Response(200, json={"code": 0, "msg": "success", "data": {
            "exposure": {"value": 8.5, "fluctuation": -0.2},
            "avg_rank": {"value": 5.2, "fluctuation": 2.62},
            "score": {"value": 6, "fluctuation": -1.1}}})
    if path == "/geo/task/get":
        return httpx.Response(200, json={"code": 0, "msg": "success", "data": {
            "scores": [{"task_id": "t1", "query_str": "Q", "platform": "yuanbao",
                         "exposure": 1, "score": 86, "avg_rank": 2}],
            "total": 1}})
    if path == "/geo/question-recommendation/list":
        return httpx.Response(200, json={"code": 0, "msg": "success", "data": {
            "total": 1, "list": [{"id": "r1", "question_text": "怎么选？",
                                  "question_type": 2, "heat_score": 88,
                                  "status": "PENDING"}]}})
    if path == "/geo/article/create":
        return httpx.Response(200, json={"code": 0, "msg": "success", "data": {"id": "a1"}})
    # 默认成功
    return httpx.Response(200, json={"code": 0, "msg": "success", "data": {}})


transport = httpx.MockTransport(handler)


def client(**kw):
    kw.setdefault("api_key", "sk-test-key-1234567890")
    kw.setdefault("team_id", "2001")
    kw.setdefault("brand_id", "1001")
    kw.setdefault("transport", transport)
    return AnswerbitClient(**kw)


print("== Answerbit 协议适配冒烟测试 ==\n")

# 1. 配置守卫
def t_config_guard():
    try:
        AnswerbitClient(api_key="")
        raise AssertionError("空 Key 应抛 ConfigError")
    except ConfigError:
        pass
    c = client()
    c.brand_id = ""  # 临时清空品牌
    try:
        c.dashboard()
        raise AssertionError("缺 brand_id 应抛 ConfigError")
    except ConfigError:
        pass
check("配置守卫（无 Key / 无 brand_id → ConfigError）", t_config_guard)

# 2. 鉴权头 + 响应解包
def t_auth_header():
    c = client()
    data = c.filter_platforms()
    req = [r for r in REQUESTS if r["path"] == "/geo/team/get/filter_platforms"][-1]
    assert req["api_key"] == "sk-test-key-1234567890", "X-API-Key 头缺失"
    assert data == {"DEEPSEEK": "deepseek", "DOUBAO": "doubao"}, "data 解包失败"
check("鉴权头（X-API-Key）+ code=0 解包 data", t_auth_header)

# 3. team_id/brand_id 自动补全
def t_payload():
    REQUESTS.clear()
    c = client()
    c.task_list(begin_date="2026-10-01", end_date="2026-10-07")
    req = [r for r in REQUESTS if r["path"] == "/geo/task/get"][-1]
    assert req["body"]["brand_id"] == "1001", "brand_id 未自动补全"
    assert req["body"]["begin_date"] == "2026-10-01"
    assert req["body"]["page_size"] == 20
check("payload 组装（brand_id 自动补全 / 分页默认值）", t_payload)

# 4. 错误分支
def t_errors():
    c = client()
    try:
        c.call("/geo/auth/401")
        raise AssertionError("401 应抛 AuthError")
    except AuthError:
        pass
    try:
        c.call("/geo/biz/error")
        raise AssertionError("code!=0 应抛 ApiError")
    except ApiError as e:
        assert e.code == 500 and e.msg == "参数错误"
    try:
        c.call("/other")
        raise AssertionError("非法 path 应抛 ApiError")
    except ApiError:
        pass
check("错误分支（401→AuthError / code!=0→ApiError / 非法 path）", t_errors)

# 5. 轮询 helper
def t_wait():
    REQUESTS.clear()
    c = client()
    result = c.wait_article(article_id="a1", interval=0.01, timeout=3)
    assert result["status"] == 1, "轮询应离开生成中"
    assert result["article"]["id"] == "a1"
check("wait_article 轮询（生成中→完成）", t_wait)

# 6. 提问具名方法
def t_prompt_get():
    REQUESTS.clear()
    c = client()
    data = c.prompt_get(query_str="推荐")
    req = [r for r in REQUESTS if r["path"] == "/geo/api/prompt/get"][-1]
    assert req["body"]["query_str"] == "推荐"
    assert req["body"]["page"] == 1
    assert data["total"] == 1
check("prompt_get（/geo/api/prompt/get 参数与响应）", t_prompt_get)

# 7. 推荐选题
def t_recommend():
    REQUESTS.clear()
    c = client()
    data = c.recommendation_list(question_type=1, page_size=50)
    req = [r for r in REQUESTS if r["path"] == "/geo/question-recommendation/list"][-1]
    assert req["body"]["question_type"] == 1 and req["body"]["page_size"] == 50
    item = data["list"][0]
    assert item["question_text"] == "怎么选？"
check("recommendation_list（推荐选题查询）", t_recommend)

# 8. 文章生成 + 仿写
def t_article_create():
    REQUESTS.clear()
    c = client()
    c.article_create(template_type="对比选购", prompt_ids=["p1"],
                     knowledge_ids=["m1"], high_ref={"url": "https://x.com/a"},
                     language="zh")
    req = [r for r in REQUESTS if r["path"] == "/geo/article/create"][-1]
    b = req["body"]
    assert b["template_type"] == "对比选购" and b["prompt_ids"] == ["p1"]
    assert b["high_ref"] == {"url": "https://x.com/a"} and b["language"] == "zh"
    assert b["brand_id"] == "1001"
check("article_create（模板/选题/知识/仿写范文参数）", t_article_create)

# 9. 文章编辑全量保护
def t_article_update():
    REQUESTS.clear()
    c = client()
    c.article_update(article_id="a1", title="新标题", main_body="正文")
    req = [r for r in REQUESTS if r["path"] == "/geo/article/update"][-1]
    assert req["body"]["main_body"] == "正文", "main_body 应随请求提交"
    try:
        c.article_update(article_id="a1", title="")
        raise AssertionError("空 title 应抛 ApiError")
    except ApiError:
        pass
check("article_update（main_body 全量提交 / 空 title 拦截）", t_article_update)

# 10. 透传
def t_call():
    c = client()
    data = c.call("/geo/material/query", {"parent_id": "0", "limit": 5})
    assert data == {}
check("通用透传 call()", t_call)

# 11. mask_key
def t_mask():
    assert mask_key("sk-test-key-1234567890") == "sk-t****7890"
    assert mask_key("") == ""
    assert mask_key("short") == "****"
check("mask_key 脱敏", t_mask)

# ---------- FastAPI 路由冒烟（TestClient，隔离 DB） ----------

print("\n== 路由冒烟（409 未配置 / 透传 / 映射端点） ==")


def t_routes():
    # 用独立 SQLite 文件，避免污染 workbench.db
    import os
    import tempfile
    tmpdir = tempfile.mkdtemp()
    os.environ["WORKBENCH_TEST_DB"] = "1"
    from app import database as dbmod
    # 替换引擎
    from sqlalchemy import create_engine
    from sqlalchemy.orm import sessionmaker
    test_engine = create_engine(f"sqlite:///{tmpdir}/t.db", connect_args={"check_same_thread": False})
    dbmod.engine = test_engine
    dbmod.SessionLocal = sessionmaker(bind=test_engine, autoflush=False, autocommit=False,
                                      expire_on_commit=False)
    from app.main import app as fastapp
    from app.answerbit import save_config, load_config
    from fastapi.testclient import TestClient

    with TestClient(fastapp) as tc:
        # 未配置 Key：映射端点 409
        r = tc.get("/api/answerbit/status")
        assert r.status_code == 200 and r.json()["configured"] is False, r.text
        r = tc.get("/api/answerbit/dashboard")
        assert r.status_code == 409, "未配置 Key 应 409"
        # 保存配置（模拟用户填 Key）——但 base_url 指向 mock 不可行（httpx transport 无法注入）
        # 此处仅验证配置写入与脱敏读取
        from app.database import SessionLocal
        s = SessionLocal()
        try:
            save_config(s, {"api_key": "sk-live-key-abcdefgh", "team_id": "2001",
                            "brand_id": "1001", "base_url": "http://127.0.0.1:9"})
            cfg = load_config(s)
            assert cfg["api_key"] == "sk-live-key-abcdefgh"
        finally:
            s.close()
        r = tc.get("/api/answerbit/config")
        assert r.json()["has_api_key"] is True
        assert r.json()["api_key"] == "sk-l****efgh", r.text
        # call 透传：会尝试真实网络 → 未配置前应 409；配置后走 mock 不可注入，
        # 改为直接验证 AnswerbitClient 与路由解耦的映射函数
        r = tc.post("/api/answerbit/call", json={"path": "/geo/article/get", "payload": {}})
        assert r.status_code in (400, 502, 409), "透传应返回可预期错误码"
check("路由冒烟（status/config/409/脱敏/透传错误处理）", t_routes)


print(f"\n== 结果：{PASS} 通过 / {FAIL} 失败 ==")
sys.exit(1 if FAIL else 0)
