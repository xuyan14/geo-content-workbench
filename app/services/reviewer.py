"""审核：规则核查 + AI 审稿，三档结论（借鉴 Omnirank 的三层审核闸）。

规则核查：绝对化用语、无来源百分比数字、篇幅、竞品名出现。
AI 审稿：pass（直接发）/ revise（局部改）/ human（要人看）。
"""
import json
import re
from typing import List, Optional

from ..ai.client import LLMClient, LLMError

ABSOLUTE_WORDS = [
    "最好", "最佳", "第一品牌", "第一名", "唯一", "顶级", "极品", "国家级",
    "世界级", "绝对", "100%有效", "永久", "彻底根治", "零风险", "万能",
]

AI_REVIEW_PROMPT = """你是 GEO 内容审稿人。严格审查文章是否遵循证据优先原则、结构是否便于 AI 引用。
【证据】
{evidence}

【文章】
{body}

输出严格的 JSON（不要输出其他内容）：
{{"verdict": "pass 或 revise 或 human", "score": 0到100整数, "issues": [{{"type": "问题类型", "detail": "具体位置与建议"}}], "comment": "一句话总评"}}
判定标准：
- pass：可发布；revise：有可自动修复的问题；human：涉及事实存疑/需业务确认。
- 出现证据中没有的数字、绝对化用语、结构混乱，均需扣分。"""


def rule_check(body: str, evidence: str = "") -> List[dict]:
    issues = []
    for w in ABSOLUTE_WORDS:
        if w in body:
            issues.append({"type": "绝对化用语", "detail": f"出现「{w}」"})
    for m in set(re.findall(r"\d+(?:\.\d+)?%", body)):
        if evidence and m not in evidence:
            issues.append({"type": "无来源数据", "detail": f"百分比 {m} 未出现在证据中，需标注来源或删除"})
    if len(body) < 400:
        issues.append({"type": "篇幅不足", "detail": f"正文仅 {len(body)} 字，建议 800+ 字"})
    if not re.search(r"^#+\s", body, re.M):
        issues.append({"type": "结构问题", "detail": "缺少 Markdown 小标题，不利于 AI 引用抓取"})
    return issues


def _parse_ai_json(text: str) -> dict:
    m = re.search(r"\{.*\}", text, re.S)
    if not m:
        return {"verdict": "human", "score": None, "issues": [], "comment": "AI 审稿返回无法解析，转人工"}
    try:
        data = json.loads(m.group(0))
        return {
            "verdict": data.get("verdict", "human"),
            "score": data.get("score"),
            "issues": data.get("issues", []),
            "comment": data.get("comment", ""),
        }
    except json.JSONDecodeError:
        return {"verdict": "human", "score": None, "issues": [], "comment": "AI 审稿 JSON 解析失败，转人工"}


def ai_review(client: LLMClient, body: str, evidence: str = "") -> dict:
    if not client.available:
        return {"verdict": "skipped", "score": None, "issues": [], "comment": "未配置 LLM，仅执行规则核查"}
    try:
        raw = client.chat(
            "你是严谨的内容审稿人，只输出 JSON。",
            AI_REVIEW_PROMPT.format(evidence=evidence[:3000], body=body[:6000]),
            temperature=0.2,
            max_tokens=1200,
        )
        return _parse_ai_json(raw)
    except LLMError as e:
        return {"verdict": "skipped", "score": None, "issues": [], "comment": f"AI 审稿失败：{e}"}


def overall_verdict(rule_issues: List[dict], ai: dict) -> str:
    """合并三档结论：pass 直接发 / revise 局部改 / human 要人看。"""
    if rule_issues:
        return "human"
    v = ai.get("verdict")
    if v == "pass":
        return "pass" if not rule_issues else "revise"
    return v or "human"
