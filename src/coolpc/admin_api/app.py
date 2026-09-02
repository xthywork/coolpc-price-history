from __future__ import annotations
from fastapi import FastAPI
from coolpc.admin_api.routers import dashboard as dashboard_router

app = FastAPI(title="原價屋管理介面")
app.include_router(dashboard_router.router)
