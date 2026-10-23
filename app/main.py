from pathlib import Path

from fastapi import FastAPI
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from sqlalchemy import text

from .database import Base, SessionLocal, engine
from .seed import seed_if_empty, seed_monitor_if_empty

BASE_DIR = Path(__file__).resolve().parent.parent

app = FastAPI(title="GeoContent Workbench", description="企业内部 GEO 内容工作台")

from .api import router  # noqa: E402

app.include_router(router)
app.mount("/static", StaticFiles(directory=BASE_DIR / "static"), name="static")
app.mount("/data", StaticFiles(directory=BASE_DIR / "static" / "data"), name="data")


@app.get("/", include_in_schema=False)
def index():
    # no-cache：SPA 单文件架构，HTML 里的 JS 会被整页缓存，禁缓存避免“改了前端浏览器不变”
    return FileResponse(BASE_DIR / "static" / "index.html", headers={"Cache-Control": "no-cache"})


@app.get("/mock.js", include_in_schema=False)
def mock_js():
    """前端演示数据层：支持以相对路径引用（后端关闭时页面可走 file:// + Mock 模式）。"""
    return FileResponse(BASE_DIR / "static" / "mock.js", media_type="application/javascript",
                        headers={"Cache-Control": "no-cache"})


@app.on_event("startup")
def startup():
    Base.metadata.create_all(bind=engine)
    # 轻量迁移：为既有库补充 brands.domain 列（SQLite 无 IF NOT EXISTS 的 ADD COLUMN）
    with engine.connect() as conn:
        cols = [row[1] for row in conn.execute(text("PRAGMA table_info(brands)"))]
        if "domain" not in cols:
            conn.execute(text("ALTER TABLE brands ADD COLUMN domain TEXT NOT NULL DEFAULT ''"))
            conn.commit()
        mq_cols = [row[1] for row in conn.execute(text("PRAGMA table_info(monitor_queries)"))]
        if "tags" not in mq_cols:
            conn.execute(text("ALTER TABLE monitor_queries ADD COLUMN tags TEXT NOT NULL DEFAULT ''"))
            conn.commit()
        doc_cols = [row[1] for row in conn.execute(text("PRAGMA table_info(documents)"))]
        if "meta" not in doc_cols:
            conn.execute(text("ALTER TABLE documents ADD COLUMN meta TEXT NOT NULL DEFAULT ''"))
            conn.commit()
        run_cols = [row[1] for row in conn.execute(text("PRAGMA table_info(monitor_runs)"))]
        if "demo" not in run_cols:
            conn.execute(text("ALTER TABLE monitor_runs ADD COLUMN demo BOOLEAN NOT NULL DEFAULT 0"))
            conn.commit()
        art_cols = [row[1] for row in conn.execute(text("PRAGMA table_info(articles)"))]
        if "source" not in art_cols:
            conn.execute(text("ALTER TABLE articles ADD COLUMN source TEXT NOT NULL DEFAULT 'ai'"))
            conn.commit()
        if "gen_meta" not in art_cols:
            conn.execute(text("ALTER TABLE articles ADD COLUMN gen_meta TEXT NOT NULL DEFAULT ''"))
            conn.commit()
    db = SessionLocal()
    try:
        seed_if_empty(db)
        seed_monitor_if_empty(db)
    finally:
        db.close()
