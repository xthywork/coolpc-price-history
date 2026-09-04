from __future__ import annotations
from fastapi import FastAPI
from pathlib import Path
from fastapi.staticfiles import StaticFiles
from coolpc.public_api.routers import api as api_router
from coolpc.public_api.routers import pages as pages_router

app = FastAPI(title="原價屋歷史價格查詢")
app.include_router(api_router.router)
app.include_router(pages_router.router)

# 兩個 app 共用同一份靜態資產（CSS、字體、原生 JS），實體目錄只有一個。
app.mount(
    "/static",
    StaticFiles(directory=str(Path(__file__).parent.parent / "web" / "static")),
    name="static",
)
