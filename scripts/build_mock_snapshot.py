#!/usr/bin/env python3
"""从本地运行实例拉取 Answerbit 真实监测数据，生成静态快照供 mock 层使用。

产出：static/data/real-snapshot.js（window.WB_REAL_SNAPSHOT = {...}）
包含：platform（真实品牌档案）、queries（全量问题+词包标签）、runs（批次）、
samples（含回答原文/引用明细）、analyses（各批次全量问题指标）。
"""
import json
import urllib.request

BASE = "http://localhost:8787"
OUT = "/Users/lucien.xu/CodeBuddy/20261014153100/geo-workbench/static/data/real-snapshot.js"


def get(path):
    with urllib.request.urlopen(BASE + path, timeout=300) as r:
        return json.loads(r.read().decode())


platform = get("/api/platform")
queries = get("/api/monitor/queries?brand_id=1")
runs = get("/api/monitor/runs?brand_id=1")

samples = []
analyses = {}
for r in runs:
    rid = r["id"]
    ss = get(f"/api/monitor/samples?run_id={rid}")
    for s in ss:
        samples.append({k: v for k, v in s.items() if not k.startswith("_")})
    try:
        a = get(f"/api/monitor/analysis?brand_id=1&run_id={rid}")
        if a.get("has_data"):
            analyses[str(rid)] = {
                "run": a.get("run"), "demo": a.get("demo"),
                "overall": a.get("overall"), "queries": a.get("queries"),
            }
    except Exception as e:
        print(f"analysis {rid} 失败: {e}")

snap = {
    "platform": platform,
    "queries": [{k: v for k, v in q.items() if not k.startswith("_")} for q in queries],
    "runs": runs,
    "samples": samples,
    "analyses": analyses,
}

js = "/* Answerbit 真实监测数据快照（mock 演示用，由 scripts/build_mock_snapshot.py 生成）*/\n" \
     "window.WB_REAL_SNAPSHOT = " + json.dumps(snap, ensure_ascii=False, separators=(",", ":")) + ";\n"
with open(OUT, "w", encoding="utf-8") as f:
    f.write(js)

import os
print(f"快照生成: 问题 {len(queries)} | 批次 {len(runs)} | 样本 {len(samples)} | 指标批次 {len(analyses)}")
print(f"文件大小: {os.path.getsize(OUT) / 1024:.0f} KB")
