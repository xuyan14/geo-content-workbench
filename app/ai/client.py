"""OpenAI-compatible 多供应商 LLM 客户端（含故障转移）。

- 供应商列表优先取数据库 Setting（页面可配），环境变量自动注册为兜底。
- 任一供应商失败自动尝试下一个（借鉴 GEORank ai_client 的 fallback 链）。
- 未配置任何供应商时 available=False，由上层服务降级为模板输出（借鉴 GeoLook 降级策略）。
"""
import os
from typing import List, Optional


class LLMError(Exception):
    pass


def _env_providers() -> List[dict]:
    """从环境变量读取内置供应商（DeepSeek / GLM / OpenAI）。"""
    presets = {
        "deepseek": ("DEEPSEEK_API_KEY", "https://api.deepseek.com/v1", "deepseek-chat"),
        "glm": ("GLM_API_KEY", "https://open.bigmodel.cn/api/paas/v4", "glm-4-flash"),
        "openai": ("OPENAI_API_KEY", "https://api.openai.com/v1", "gpt-4o-mini"),
    }
    providers = []
    for name, (key_env, default_url, default_model) in presets.items():
        key = os.environ.get(key_env, "").strip()
        if key:
            providers.append(
                {
                    "name": name,
                    "base_url": os.environ.get(f"{name.upper()}_BASE_URL", default_url),
                    "model": os.environ.get(f"{name.upper()}_MODEL", default_model),
                    "api_key": key,
                    "market": "both",
                }
            )
    return providers


def normalize_url(base_url: str) -> str:
    """兼容填基础地址或完整端点两种写法（借鉴 GEOFlow 的接入体验）。"""
    url = base_url.rstrip("/")
    if url.endswith("/chat/completions"):
        return url
    return url + "/chat/completions"


class LLMClient:
    def __init__(self, providers: Optional[List[dict]] = None):
        self.providers = [p for p in (providers or []) if p.get("api_key") and p.get("model")]

    @property
    def available(self) -> bool:
        return bool(self.providers)

    def chat(self, system: str, user: str, temperature: float = 0.7, max_tokens: int = 4000) -> str:
        if not self.providers:
            raise LLMError("未配置任何可用的 LLM 供应商")
        import httpx

        errors = []
        for p in self.providers:
            url = normalize_url(p["base_url"])
            try:
                resp = httpx.post(
                    url,
                    headers={"Authorization": f"Bearer {p['api_key']}"},
                    json={
                        "model": p["model"],
                        "messages": [
                            {"role": "system", "content": system},
                            {"role": "user", "content": user},
                        ],
                        "temperature": temperature,
                        "max_tokens": max_tokens,
                    },
                    timeout=180,
                )
                resp.raise_for_status()
                data = resp.json()
                return data["choices"][0]["message"]["content"]
            except Exception as e:  # noqa: BLE001 - 逐个供应商降级
                errors.append(f"{p.get('name')}({p.get('model')}): {e}")
        raise LLMError("所有供应商均失败：" + " | ".join(errors))

    def ping(self) -> List[dict]:
        """逐个供应商测试连通性，返回 [{name, ok, error}]。"""
        import httpx

        results = []
        for p in self.providers:
            try:
                resp = httpx.post(
                    normalize_url(p["base_url"]),
                    headers={"Authorization": f"Bearer {p['api_key']}"},
                    json={
                        "model": p["model"],
                        "messages": [{"role": "user", "content": "ping"}],
                        "max_tokens": 8,
                    },
                    timeout=30,
                )
                resp.raise_for_status()
                results.append({"name": p.get("name"), "model": p.get("model"), "ok": True, "error": ""})
            except Exception as e:  # noqa: BLE001
                results.append({"name": p.get("name"), "model": p.get("model"), "ok": False, "error": str(e)})
        return results
