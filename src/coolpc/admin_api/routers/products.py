from __future__ import annotations
from pathlib import Path
from urllib.parse import urlencode
from fastapi import APIRouter, Depends, Request, Form
from fastapi.templating import Jinja2Templates
from fastapi.responses import RedirectResponse
from sqlalchemy.orm import Session
from coolpc.admin_api.dependencies import get_session
from coolpc.query_types import OptionalInt, OptionalBool
from coolpc.db.models import Category, MergeLog, Product
from coolpc.search.service import SearchFilters, search_products
from coolpc.merging.service import merge_products, undo_merge, MergeError

router = APIRouter()
templates = Jinja2Templates(directory=str(Path(__file__).parent.parent / "templates"))


@router.get("/products")
def product_search(
    request: Request, q: str | None = None, category_id: OptionalInt = None,
    is_active: OptionalBool = None, session: Session = Depends(get_session),
):
    filters = SearchFilters(q=q, category_id=category_id, is_active=is_active, limit=100)
    products, total = search_products(session, filters)
    return templates.TemplateResponse(request, "products.html", {
        "products": products, "total": total,
        "categories": session.query(Category).order_by(Category.name).all(),
        "query": {"q": q or "", "category_id": category_id},
    })


@router.get("/merge")
def merge_form(request: Request, message: str | None = None, error: str | None = None,
               session: Session = Depends(get_session)):
    logs = session.query(MergeLog).order_by(MergeLog.merged_at.desc()).limit(50).all()
    log_rows = [
        {"log": log, "source": session.get(Product, log.source_product_id),
         "target": session.get(Product, log.target_product_id)}
        for log in logs
    ]
    return templates.TemplateResponse(request, "merge.html", {
        "message": message, "error": error, "log_rows": log_rows,
    })


@router.post("/merge")
def do_merge(source_id: int = Form(...), target_id: int = Form(...),
             session: Session = Depends(get_session)):
    try:
        merge_products(session, source_id, target_id)
        session.commit()
        qs = urlencode({"message": "合併成功"})
        return RedirectResponse(url=f"/merge?{qs}", status_code=303)
    except MergeError as exc:
        session.rollback()
        qs = urlencode({"error": str(exc)})
        return RedirectResponse(url=f"/merge?{qs}", status_code=303)


@router.post("/merge/{merge_log_id}/undo")
def do_undo(merge_log_id: int, session: Session = Depends(get_session)):
    try:
        undo_merge(session, merge_log_id)
        session.commit()
        qs = urlencode({"message": "已復原合併"})
        return RedirectResponse(url=f"/merge?{qs}", status_code=303)
    except MergeError as exc:
        session.rollback()
        qs = urlencode({"error": str(exc)})
        return RedirectResponse(url=f"/merge?{qs}", status_code=303)
