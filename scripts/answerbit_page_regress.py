"""页面功能回归：5 个页面逐页渲染 + Answerbit 真实数据联动检查 + 无 JS 报错。"""
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import httpx  # noqa: E402
from playwright.sync_api import sync_playwright

BASE = "http://localhost:8787"
OUT = Path(__file__).resolve().parent.parent / "logs"
OUT.mkdir(exist_ok=True)

# 页面 -> 关键断言（页面出现即为通过；附加内容检查）
PAGES = [
    ("#/monitor", "监测中心", ["AI提及率", "可见引用份额", "AI推荐率（首推率）", "AI推荐率（前三位率）"]),
    ("#/topics", "选题库", ["已生成"]),
    ("#/answers", "大模型回答记录", []),
    ("#/knowledge", "知识库", []),
    ("#/factory", "内容工厂", ["AI 生成", "本地上传"]),
]

fails = []
with sync_playwright() as p:
    b = p.chromium.launch()
    page = b.new_page(viewport={"width": 1440, "height": 1000})
    errs = []
    page.on("pageerror", lambda e: errs.append(str(e)))
    page.on("console", lambda m: errs.append(m.text) if m.type == "error" else None)

    for frag, name, kws in PAGES:
        errs.clear()
        page.goto(f"{BASE}/{frag}")
        page.wait_for_timeout(600)
        # 等待视图渲染完成（监测中心接口较多，轮询直至 KPI/表格出现或 3s 超时）
        page.wait_for_selector("#view .grid, #view table, #view .shadow", timeout=3000)
        page.wait_for_timeout(600)
        html = page.content()
        ok_text = page.locator("#view").inner_text() if page.locator("#view").count() else html
        missing = [k for k in kws if k not in ok_text]
        view_len = len(ok_text.strip())
        js_err = [e for e in errs if "favicon" not in e]
        status = "PASS" if (view_len > 50 and not missing and not js_err) else "FAIL"
        print(f"  {status}  {name:<10} 内容 {view_len}B | 缺失: {missing or '无'} | JS错误: {js_err or '无'}")
        if status == "FAIL":
            fails.append((name, missing, js_err))
        page.screenshot(path=str(OUT / f"regress-{frag.replace('#/', '')}.png"))

    # 交互冒烟：监测中心批次切换（下拉筛选）
    page.goto(f"{BASE}/#/monitor")
    page.wait_for_timeout(1000)
    chips = page.locator("#mon-body button")
    if chips.count() > 2:
        chips.nth(2).click()  # 切换指标
        page.wait_for_timeout(600)
        print(f"  {'PASS' if not errs else 'FAIL'}  指标切换交互 | JS错误: {errs or '无'}")
    b.close()

# Answerbit 端点在服务重启后仍连通（配置持久化验证）
with httpx.Client(timeout=30) as hc:
    r = hc.get(f"{BASE}/api/answerbit/status").json()
    print(f"  {'PASS' if r['configured'] else 'FAIL'}  Answerbit 配置持久化（configured={r['configured']}）")
    if not r["configured"]:
        fails.append(("answerbit-status", "configured=False", None))
    r = hc.post(f"{BASE}/api/answerbit/config/test").json()
    print(f"  {'PASS' if r.get('ok') else 'FAIL'}  Answerbit 连接测试（latency={r.get('latency_ms')}ms）")
    if not r.get("ok"):
        fails.append(("answerbit-test", r, None))

print(f"\n== 回归结果：{'全部通过' if not fails else f'{len(fails)} 项失败: {fails}'} ==")
sys.exit(1 if fails else 0)
