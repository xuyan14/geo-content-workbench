"""选题拓词：LLM 生成 + 模板降级（借鉴 GEORank 的画像化 8 维拓词）。"""
import json
import re
from typing import List

from ..ai.client import LLMClient, LLMError
from ..models import Brand

DIMENSIONS = ["语义泛化", "使用场景", "商业意图", "推荐榜单", "评测对比", "品牌词", "问答长尾", "技术方案"]

EXPAND_PROMPT = """你是 GEO 选题专家。基于品牌信息，围绕种子词生成覆盖 8 个维度（语义泛化/使用场景/商业意图/推荐榜单/评测对比/品牌词/问答长尾/技术方案）的选题。

【品牌】{name}（{industry}），卖点：{selling_points}

【种子词】{seeds}

生成 {n} 条选题，输出严格 JSON 数组（不要其他内容）：
[{{"keyword": "选题", "intent": "buyer_intent 或 education 或 probe", "dimension": "维度", "market": "cn 或 global"}}]
要求：中文题打 cn 市场、英文题打 global；关键词是用户会问 AI 的自然问题。"""

# 降级模板：种子词 × 意图句式
_FALLBACK_PATTERNS = [
    ("{k}怎么选", "buyer_intent", "评测对比"),
    ("{k}哪家好", "buyer_intent", "推荐榜单"),
    ("{k}多少钱", "buyer_intent", "商业意图"),
    ("{k}对比测评", "buyer_intent", "评测对比"),
    ("{k}适合什么场景", "education", "使用场景"),
    ("{k}常见问题", "education", "问答长尾"),
    ("{k}注意事项", "education", "问答长尾"),
    ("{k}最新趋势", "probe", "语义泛化"),
]


def expand(client: LLMClient, brand: Brand, seed_keywords: str, n: int = 8) -> List[dict]:
    seed_list = [s.strip() for s in seed_keywords.replace("，", ",").split(",") if s.strip()] or [brand.name]
    seeds = ", ".join(seed_list)
    if client.available:
        try:
            raw = client.chat(
                "你是 GEO 选题专家，只输出 JSON。",
                EXPAND_PROMPT.format(
                    name=brand.name,
                    industry=brand.industry or "未填写",
                    selling_points=brand.selling_points or "见知识库",
                    seeds=seeds,
                    n=n,
                ),
                temperature=0.8,
                max_tokens=2000,
            )
            m = re.search(r"\[.*\]", raw, re.S)
            if m:
                items = json.loads(m.group(0))
                return [
                    {
                        "keyword": it.get("keyword", "")[:200],
                        "intent": it.get("intent", "education"),
                        "dimension": it.get("dimension", "问答长尾"),
                        "market": it.get("market", "cn"),
                    }
                    for it in items
                    if it.get("keyword")
                ][:n]
        except (LLMError, json.JSONDecodeError):
            pass

    # 模板降级：逐个种子词套用意图句式
    results = []
    i = 0
    while len(results) < n:
        seed = seed_list[i % len(seed_list)]
        pattern, intent, dim = _FALLBACK_PATTERNS[(i // len(seed_list)) % len(_FALLBACK_PATTERNS)]
        results.append({"keyword": pattern.format(k=seed), "intent": intent, "dimension": dim, "market": "cn"})
        i += 1
    return results
