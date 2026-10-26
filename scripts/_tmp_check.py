import time
from playwright.sync_api import sync_playwright

with sync_playwright() as p:
    b = p.chromium.launch()
    pg = b.new_page(viewport={"width": 1440, "height": 900})
    pg.goto("http://localhost:8787", wait_until="domcontentloaded")
    pg.evaluate("localStorage.setItem('wb_mock','1')")
    pg.goto("http://localhost:8787", wait_until="networkidle")
    pg.wait_for_timeout(1500)
    for name in ["监测中心", "大模型回答记录", "知识库", "内容工厂", "选题库"]:
        pg.click(f"nav >> text={name}")
        pg.wait_for_timeout(2500)
        t = pg.inner_text("#view")
        loading = "加载中" in t or "加载回答记录中" in t
        print(f"{name}: {'仍在加载' if loading else 'OK'} | {len(t)} 字符")
    b.close()
