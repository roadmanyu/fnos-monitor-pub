"""FastAPI 入口：API + 采集循环 + 静态前端。"""
from __future__ import annotations

import logging
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles

from app.api.v1 import alerts, auth, disks, docker, meta, metrics
from app.collectors.loop import CollectorLoop
from app.config import data_dir, load_config
from app.storage.sqlite_store import Store

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s [%(name)s] %(message)s",
)
log = logging.getLogger("fnos-monitor")

store: Store | None = None
collector: CollectorLoop | None = None
cfg = None


@asynccontextmanager
async def lifespan(app: FastAPI):
    global store, collector, cfg
    cfg = load_config()
    db_path = data_dir() / "monitor.db"
    store = Store(db_path)
    collector = CollectorLoop(cfg, store)
    collector.start()
    log.info("fnos-monitor started; db=%s", db_path)
    yield
    log.info("fnos-monitor stopping")


app = FastAPI(title="fnOS Monitor", version="0.1.0", lifespan=lifespan)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

API = "/api/v1"
app.include_router(auth.router, prefix=API)
app.include_router(meta.router, prefix=API)
app.include_router(metrics.router, prefix=API)
app.include_router(disks.router, prefix=API)
app.include_router(docker.router, prefix=API)
app.include_router(alerts.router, prefix=API)

# 静态前端：优先 backend/app/static，其次 web/dist
_static_candidates = [
    Path(__file__).resolve().parent / "static",
    Path(__file__).resolve().parents[2] / "web" / "dist",
]
_static_dir = next((p for p in _static_candidates if p.is_dir() and (p / "index.html").exists()), None)

if _static_dir:
    assets = _static_dir / "assets"
    if assets.is_dir():
        app.mount("/assets", StaticFiles(directory=assets), name="assets")

    @app.get("/")
    def index():
        return FileResponse(_static_dir / "index.html")

    @app.get("/{full_path:path}")
    def spa(full_path: str):
        # 勿吞掉 API：未匹配的 /api/* 返回 JSON 404
        if full_path == "api" or full_path.startswith("api/"):
            return JSONResponse(
                status_code=404,
                content={"detail": {"code": "not_found", "message": f"/{full_path}"}},
            )
        candidate = _static_dir / full_path
        if candidate.is_file():
            return FileResponse(candidate)
        return FileResponse(_static_dir / "index.html")
else:
    log.warning("web dist not found; API-only mode")


def run():
    import uvicorn

    c = load_config()
    uvicorn.run(
        "app.main:app",
        host=c.server.host,
        port=c.server.port,
        reload=False,
    )


if __name__ == "__main__":
    run()
