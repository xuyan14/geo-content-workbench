# GeoContent Workbench · GEO 内容工作台

面向品牌运营团队的 GEO（生成式引擎优化）一站式工作台：追踪品牌在 AI 搜索中的可见度，并基于监测数据驱动内容生产与发布。

```
AI 问答监测 → 可见度洞察 → 选题沉淀 → 内容生产 → 审核发布
```

- **双数据源**：已配置 [腾讯 Answerbit GEO 平台](https://answerbit.qq.com) OpenAPI 时展示真实监测数据；未接入自动回退本地演示数据（7 天爬升演示批次），体验无差异
- **全流程可走通**：未配置任何 LLM 时生成/审稿/拓词自动降级（模板草稿 / 规则核查），流程不中断
- **离线模式**：后端不可达时自动切换纯前端 mock 数据层，页面完整可逛

## 功能总览

| 模块 | 能力 |
|---|---|
| **监测中心** | KPI 四卡（AI 提及率 / 可见引用份额 / 首推率 / 前三位率）；品牌 + 竞品按日趋势曲线（三指标切换）；竞品提及排行；问题 / 时间 / 模型 / 标签四维筛选（日历区间选择） |
| **选题库** | 监测问题统一管理（241 问题全量真实指标）；7 维词包标签筛选；多选批量发起采样；与本地选题联动（「已生成」标记） |
| **大模型回答记录** | 每次采样的原始回答原文；品牌名及别名高亮；位次 / 引用域名 / 提及竞品 / 引用官网标记；时间 / 模型 / 判定 / 关键字筛选 |
| **知识库** | 知识卡治理（审核三标记 + 差异对照 + 引文核对）；知识库文档三式入库（粘贴 / 上传 / URL 抓取），结构化分块进入证据池 |
| **内容工厂** | AI 生成向导（5 种文体模板 / 高引用范文仿写双模式，目标模型多选）；本地上传轨道；规则核查 + AI 审稿双重把关；审核 → 发布（dry-run / webhook） |

**全项目仅关注四个模型**：DeepSeek、豆包、千问、元宝。

## 快速开始

```bash
python3 -m venv .venv && .venv/bin/pip install -r requirements.txt
.venv/bin/python -m uvicorn app.main:app --port 8787
# 打开 http://localhost:8787（自动建库并写入演示种子数据）
```

或直接 `bash scripts/start.sh`（自动处理进程清理 / venv / 就绪探测）。

> 内置演示数据（品牌档案「星野优选」、监测问题集、知识卡）均为**虚构数据**，仅用于开箱演示；可在 `app/seed.py` 与 `app/real_queries.py` 中替换为任意真实品牌与问题集。

## 接入 LLM（可选，强烈建议）

任意 OpenAI-compatible 供应商（DeepSeek / GLM / 豆包 / OpenAI…）均可：

```bash
export DEEPSEEK_API_KEY=sk-xxx   # 或 GLM_API_KEY / OPENAI_API_KEY
```

配置多个时按顺序故障转移；未配置时全流程模板降级仍可走通。

## 接入腾讯 Answerbit GEO 平台（可选）

1. 配置 API Key（任一方式）：
   - 环境变量：`ANSWERBIT_API_KEY` / `ANSWERBIT_TEAM_ID` / `ANSWERBIT_BRAND_ID`
   - 或调用 `PUT /api/answerbit/config`（Key 落库时脱敏存储）
2. 配置成功后本地监测端点（`/api/monitor/*`）自动切换为平台真实数据，失败自动回退

内置 `POST /api/answerbit/call` 全接口通用透传（95 个平台接口，`{path: "/geo/...", payload}`），另有 dashboard / 趋势 / 回答 / 推荐选题 / 文章生成等语义化映射端点，详见 `docs/技术方案.md`。

## 架构

```
FastAPI (uvicorn :8787) ── SQLAlchemy 2.0 ── SQLite（data/workbench.db，自动建表+迁移+seed）
        │
        ├── app/api.py            本地业务端点（/api）
        ├── app/api_answerbit.py  Answerbit 适配（透传/映射/双数据源兼容层）
        ├── app/services/         生成·检索·监测·审稿·拓词·发布
        ├── app/ai/client.py      OpenAI-compatible 多供应商客户端（故障转移）
        └── static/index.html     单文件 SPA（Tailwind CDN + vanilla JS，无构建链）
```

- 后端：Python 3.9+ / FastAPI / SQLAlchemy / httpx
- 前端：单文件原生 SPA，手绘 SVG 图表，无 Node 构建链
- 详见 [docs/技术方案.md](docs/技术方案.md)（字段级接口形状 / 算法规格 / 集成协议）

## 文档

- [docs/产品文档.md](docs/产品文档.md) —— 产品逻辑、模块交互、视觉规范（复现级规格）
- [docs/技术方案.md](docs/技术方案.md) —— 架构、数据模型、API、集成设计、硬参数
- [docs/设计方案.md](docs/设计方案.md) —— 早期产品设计论证

## 回归脚本

```bash
.venv/bin/python scripts/answerbit_e2e.py          # Answerbit 只读接口 E2E（需 env 配置）
.venv/bin/python scripts/answerbit_page_regress.py # Playwright 五页回归
.venv/bin/python scripts/test_answerbit.py         # 无 Key 冒烟（MockTransport）
```

## 致谢

基于对 [Omnirank-GEO](https://github.com/OmnirankGEO/Omnirank-GEO)、[GEORank](https://github.com/yaojingang/GEORank)、[GeoLook](https://github.com/aigclink/geolook) 三个开源 GEO 项目的调研重构，聚焦企业内容工程链路。
