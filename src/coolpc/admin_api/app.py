from __future__ import annotations
from fastapi import FastAPI
from pathlib import Path
from fastapi.staticfiles import StaticFiles
from coolpc.admin_api.routers import dashboard as dashboard_router
from coolpc.admin_api.routers import products as products_router
from coolpc.admin_api.routers import similarity as similarity_router

app = FastAPI(title="原價屋管理介面")
app.include_router(dashboard_router.router)
app.include_router(products_router.router)
app.include_router(similarity_router.router)

# 兩個 app 共用同一份靜態資產（CSS、字體、原生 JS），實體目錄只有一個。
app.mount(
    "/static",
    StaticFiles(directory=str(Path(__file__).parent.parent / "web" / "static")),
    name="static",
)
