from __future__ import annotations
from fastapi import FastAPI
from coolpc.public_api.routers import api as api_router

app = FastAPI(title="原價屋歷史價格查詢")
app.include_router(api_router.router)
