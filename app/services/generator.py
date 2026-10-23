"""内容生成：文体模板 / 范文仿写 + 证据注入 + LLM/模板双轨。

借鉴：
- Omnirank writing/：模板化文体、证据优先系统提示词、无 LLM 降级
- GeoLook generate.py：--draft 初稿 + 模板降级
"""
import json
from typing import List, Optional

from ..ai.client import LLMClient, LLMError
from ..models import Brand, Chunk, Topic

IMITATE_TEMPLATE = "范文仿写"

TEMPLATES = {
    "对比选购": {
        "title_hint": "怎么选？{keyword}全维度对比指南",
        "sections": "核心结论前置 / 选购标准清单 / 品牌与竞品逐项对比表 / 不同需求推荐 / 常见疑问",
    },
    "案例实证": {
        "title_hint": "{keyword}真实案例与数据复盘",
        "sections": "背景与问题 / 解决方案（含产品介入点）/ 量化结果（必须来自证据）/ 复盘要点",
    },
    "风险避坑": {
        "title_hint": "{keyword}的5个常见风险与避坑指南",
        "sections": "风险清单（逐条说明后果）/ 判断标准 / 正确做法 / 一句话结论",
    },
    "FAQ问答": {
        "title_hint": "{keyword}常见问题权威解答",
        "sections": "以问答形式覆盖：是什么 / 怎么选 / 多少钱 / 注意什么（每个回答先给结论再展开）",
    },
    "场景方案": {
        "title_hint": "{keyword}场景化解决方案",
        "sections": "场景描述 / 痛点拆解 / 分步方案 / 所需能力清单 / 效果预期",
    },
}

SYSTEM_PROMPT = """你是 GEO（生成式引擎优化）内容写手，为品牌生产能被 AI 搜索引擎引用的高质量内容。写作铁律：
1. 证据优先：只使用【证据】中给出的事实与数字，禁止编造；引用数字时标注来源（如：据《xxx》）。
2. 结论前置：每个小节第一句给结论，便于 AI 引用抓取。
3. 结构清晰：使用 Markdown 小标题、列表、表格；关键概念给出明确「定义句」。
4. 口吻：{tone}；不堆砌绝对化用语（最好/第一/顶级/100% 等）。
5. 篇幅 1200 字左右，输出纯 Markdown，第一行是「# 文章标题」。"""

USER_PROMPT = """【品牌信息】
品牌：{brand}（别名：{aliases}）
行业：{industry}
核心卖点：
{selling_points}
竞品：{competitors}

【证据（来自知识库，只能使用这些事实）】
{evidence}

【写作任务】
选题/关键词：{keyword}（意图：{intent}）
文体模板：{template}
必须覆盖的章节：{sections}

请基于以上证据与品牌信息，围绕选题写一篇 {template} 类型的文章。"""

REF_GUIDE = """【参考范文结构（高引用范文特征）】
范文标题：{ref_title}
范文结构大纲：
{outline}

写作要求：学习上述范文的章节结构、行文节奏与信息密度（如结论前置、小标题粒度、列表/表格用法），按同样的结构组织本篇内容；但正文事实只能来自【证据】，禁止复述或改写范文中的具体内容与表述。"""

USER_PROMPT_REF = """【品牌信息】
品牌：{brand}（别名：{aliases}）
行业：{industry}
核心卖点：
{selling_points}
竞品：{competitors}

【证据（来自知识库，只能使用这些事实）】
{evidence}

【写作任务】
选题/关键词：{keyword}（意图：{intent}）
写作方式：范文仿写（{ref_title}）
{ref_guide}

请基于证据与品牌信息，围绕选题，仿照参考范文的结构写一篇文章。"""

FALLBACK_NOTE = "> ⚠️ 本篇为模板降级草稿（未配置 AI 模型或模型调用失败）。结构和证据已就位，配置模型后可重新生成。"


def build_evidence_text(chunks: List[Chunk]) -> str:
    if not chunks:
        return "（知识库暂无相关证据，仅可使用品牌信息中已核实的内容）"
    lines = []
    for i, c in enumerate(chunks, 1):
        src = f"（来自《{c.document_title}》）" if hasattr(c, "document_title") else ""
        text = c.text.replace("\n", " ")[:400]
        lines.append(f"[证据{i}] {text}{src}")
    return "\n".join(lines)


def fallback_title(brand: Brand, topic: Topic, template: str) -> str:
    hint = TEMPLATES.get(template, TEMPLATES["对比选购"])["title_hint"]
    kw = topic.keyword
    # 选题本身是疑问句时，避免句式叠加（如「怎么选？X怎么选」）
    if any(q in kw for q in ("怎么", "如何", "哪", "多少", "什么", "吗")):
        return f"{kw}——{brand.name}{template}指南"
    return hint.format(keyword=kw)


def fallback_draft(brand: Brand, topic: Topic, template: str, chunks: List[Chunk]) -> str:
    """无 LLM 时的模板降级草稿：把证据按文体模板组织成可编辑初稿。"""
    sections = TEMPLATES.get(template, TEMPLATES["对比选购"])["sections"]
    points = [p.strip() for p in (brand.selling_points or "").splitlines() if p.strip()]
    comp = [p.strip() for p in (brand.competitors or "").splitlines() if p.strip()]

    lines = [f"# {fallback_title(brand, topic, template)}", "", FALLBACK_NOTE, "", "## 核心结论", ""]
    lines.append(f"围绕「{topic.keyword}」，{brand.name}的核心主张：")
    for p in points[:5]:
        lines.append(f"- {p}")
    lines += ["", f"## 覆盖章节（{template}）", f"{sections}", ""]

    if chunks:
        lines += ["## 品牌事实（来自知识库证据，请整理进正文）", ""]
        for i, c in enumerate(chunks, 1):
            lines.append(f"**[证据{i}]** {c.text[:300]}")
            lines.append("")
    if comp:
        lines += ["## 竞品参考（对比时保持客观）", ", ".join(comp), ""]
    lines += [
        "## 常见疑问",
        f"- {topic.keyword}怎么选？→ 依据证据补充",
        f"- {topic.keyword}要注意什么？→ 依据证据补充",
        "",
        "## 待人工补充",
        "- 替换降级提示为正式内容",
        "- 核对所有数字的来源标注",
    ]
    return "\n".join(lines)


def extract_title(md: str) -> str:
    for line in md.splitlines():
        if line.strip().startswith("# "):
            return line.strip().lstrip("# ").strip()
    return md.strip().splitlines()[0][:60] if md.strip() else "未命名"


def structure_outline(ref_body: str) -> str:
    """提取范文结构骨架：Markdown 标题行；无标题时退化为开头摘要。"""
    heads = [ln.strip().lstrip("#").strip() for ln in (ref_body or "").splitlines()
             if ln.strip().startswith("#")]
    if heads:
        return "\n".join(f"- {h}" for h in heads[:20])
    excerpt = " ".join((ref_body or "").split())[:300]
    return f"（范文无小标题，参考其行文节奏）开头节选：{excerpt}…"


def fallback_draft_imitate(brand: Brand, topic: Topic, ref_title: str, outline: str, chunks: List[Chunk]) -> str:
    """范文仿写的模板降级草稿：按范文大纲占位，证据就位待整理。"""
    points = [p.strip() for p in (brand.selling_points or "").splitlines() if p.strip()]
    lines = [
        f"# {topic.keyword}——{brand.name}范文仿写指南", "",
        FALLBACK_NOTE, "",
        f"## 仿写对象：{ref_title}", "",
        "## 范文结构大纲（生成正文时逐节展开）", outline, "",
        "## 核心结论", "",
    ]
    lines.append(f"围绕「{topic.keyword}」，{brand.name}的核心主张：")
    for p in points[:5]:
        lines.append(f"- {p}")
    if chunks:
        lines += ["", "## 品牌事实（来自知识库证据，请整理进各章节）", ""]
        for i, c in enumerate(chunks, 1):
            lines.append(f"**[证据{i}]** {c.text[:300]}")
            lines.append("")
    lines += ["", "## 待人工补充", "- 按范文大纲逐节撰写正式内容", "- 核对所有数字的来源标注"]
    return "\n".join(lines)


def generate(
    client: LLMClient,
    brand: Brand,
    topic: Topic,
    template: str,
    chunks: List[Chunk],
    reference: Optional[dict] = None,
) -> dict:
    """生成文章，返回 {title, body, evidence, degraded}。

    reference: {title, body} 非空时走「范文仿写」——提取范文结构特征注入提示词。
    """
    evidence_text = build_evidence_text(chunks)
    imitate = bool(reference and (reference.get("body") or "").strip())
    ref_title = (reference or {}).get("title") or "（未命名范文）"
    tpl = TEMPLATES.get(template, TEMPLATES["对比选购"])
    degraded = False

    if client.available:
        try:
            system = SYSTEM_PROMPT.format(tone=brand.tone or "专业可信")
            if imitate:
                ref_guide = REF_GUIDE.format(
                    ref_title=ref_title, outline=structure_outline(reference["body"]))
                user = USER_PROMPT_REF.format(
                    brand=brand.name,
                    aliases=brand.aliases or "无",
                    industry=brand.industry or "未填写",
                    selling_points=brand.selling_points or "见知识库证据",
                    competitors=brand.competitors or "未填写",
                    evidence=evidence_text,
                    keyword=topic.keyword,
                    intent={"buyer_intent": "买家意图（价格/推荐/比较/替代）", "education": "需求教育", "probe": "探测"}.get(
                        topic.intent, topic.intent),
                    ref_title=ref_title,
                    ref_guide=ref_guide,
                )
            else:
                user = USER_PROMPT.format(
                    brand=brand.name,
                    aliases=brand.aliases or "无",
                    industry=brand.industry or "未填写",
                    selling_points=brand.selling_points or "见知识库证据",
                    competitors=brand.competitors or "未填写",
                    evidence=evidence_text,
                    keyword=topic.keyword,
                    intent={"buyer_intent": "买家意图（价格/推荐/比较/替代）", "education": "需求教育", "probe": "探测"}.get(
                        topic.intent, topic.intent),
                    template=template,
                    sections=tpl["sections"],
                )
            body = client.chat(system, user)
            return {
                "title": extract_title(body),
                "body": body,
                "evidence": evidence_text,
                "degraded": False,
            }
        except LLMError:
            degraded = True

    if imitate:
        return {
            "title": fallback_title(brand, topic, IMITATE_TEMPLATE).replace(
                f"{brand.name}{IMITATE_TEMPLATE}指南", f"{brand.name}范文仿写指南"),
            "body": fallback_draft_imitate(brand, topic, ref_title,
                                           structure_outline(reference["body"]), chunks),
            "evidence": evidence_text,
            "degraded": True,
        }
    return {
        "title": fallback_title(brand, topic, template),
        "body": fallback_draft(brand, topic, template, chunks),
        "evidence": evidence_text,
        "degraded": True,
    }
