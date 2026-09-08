from __future__ import annotations
import json
from pathlib import Path
from urllib.parse import urlencode
from fastapi import APIRouter, Depends, HTTPException, Request, Form
from fastapi.templating import Jinja2Templates
from fastapi.responses import RedirectResponse
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session
from coolpc.admin_api.dependencies import get_session
from coolpc.query_types import OptionalInt, OptionalBool
from coolpc.db.models import Category, MergeLog, Product, Subcategory
from coolpc.search.service import SearchFilters, search_products, search_products_and
from coolpc.merging.service import merge_products, undo_merge, MergeError
from coolpc.public_api.routers.pages import (
    PAGE_SIZE_OPTIONS, DEFAULT_PAGE_SIZE, _resolve_page_size, _build_page_list,
)

router = APIRouter()
templates = Jinja2Templates(directory=str(Path(__file__).parent.parent / "templates"))


def _get_product_or_404(session: Session, product_id: int) -> Product:
    product = session.get(Product, product_id)
    if product is None:
        raise HTTPException(status_code=404, detail="商品不存在")
    return product


@router.get("/products")
def product_search(
    request: Request, q: str | None = None, category_id: OptionalInt = None,
    is_active: OptionalBool = None, page: int = 1, page_size: str = str(DEFAULT_PAGE_SIZE),
    session: Session = Depends(get_session),
):
    page = max(page, 1)
    page_size, effective_page_size = _resolve_page_size(page_size)
    filters = SearchFilters(
        q=q, q_match="and", category_id=category_id, is_active=is_active,
        limit=effective_page_size, offset=(page - 1) * effective_page_size,
    )
    products, total = search_products(session, filters)
    total_pages = max((total + effective_page_size - 1) // effective_page_size, 1)

    query_params = {k: v for k, v in {
        "q": q, "category_id": category_id, "is_active": is_active, "page_size": page_size,
    }.items() if v not in (None, "")}

    return templates.TemplateResponse(request, "products.html", {
        "products": products, "total": total,
        "categories": session.query(Category).order_by(Category.sort_order.asc().nulls_last(), Category.name).all(),
        "query": {"q": q or "", "category_id": category_id, "is_active": is_active, "page_size": page_size},
        "query_string": urlencode(query_params),
        "page": page,
        "total_pages": total_pages,
        "page_list": _build_page_list(page, total_pages),
        "page_size_options": PAGE_SIZE_OPTIONS,
    })


# 這個端點必須註冊在 /products/{product_id} 之前，否則 "search-json" 會先被
# 當成 product_id 吃掉。
@router.get("/products/search-json")
def product_search_json(q: str = "", session: Session = Depends(get_session)):
    if not q.strip():
        return []
    # AND 語意：要求所有空白分隔的片段都命中，才能精確命中查詢的那個商品
    # 本身，完全不退回 OR 後備——寧可查無結果，也不要讓不精確的商品混進來。
    # 不限制筆數，符合條件的商品要全部列出來。
    products = search_products_and(session, q)
    return [
        {"id": p.id, "name": p.current_name, "price": p.current_price, "is_active": p.is_active}
        for p in products
    ]


@router.get("/products/{product_id}")
def product_detail(
    request: Request, product_id: int, message: str | None = None,
    session: Session = Depends(get_session),
):
    product = _get_product_or_404(session, product_id)
    category = session.get(Category, product.category_id)
    subcategory = session.get(Subcategory, product.subcategory_id)
    merged_into = session.get(Product, product.merged_into_id) if product.merged_into_id else None
    categories = session.query(Category).order_by(Category.sort_order.asc().nulls_last(), Category.name).all()
    subcategory_rows = session.query(Subcategory).order_by(Subcategory.category_id, Subcategory.name).all()
    subcategories = [{"id": s.id, "category_id": s.category_id, "label": s.label} for s in subcategory_rows]
    # 防止分類/子分類名稱裡剛好出現 "</script>" 提早把整段 <script> 標籤截斷。
    subcategories_json = json.dumps(subcategories, ensure_ascii=False).replace("</", "<\\/")
    return templates.TemplateResponse(request, "product_detail.html", {
        "product": product, "category": category, "subcategory": subcategory,
        "merged_into": merged_into, "categories": categories,
        "subcategories_json": subcategories_json,
        "message": message,
    })


@router.post("/products/{product_id}")
def product_update(
    product_id: int,
    current_name: str = Form(...),
    brand: str = Form(""),
    model: str = Form(""),
    current_status: str = Form(""),
    current_price: int = Form(...),
    category_id: int = Form(...),
    subcategory_id: int = Form(...),
    is_active: bool = Form(...),
    session: Session = Depends(get_session),
):
    product = _get_product_or_404(session, product_id)
    if product.merged_into_id is not None:
        raise HTTPException(status_code=400, detail="已合併的商品不可編輯")
    subcategory = session.get(Subcategory, subcategory_id)
    if subcategory is None or subcategory.category_id != category_id:
        raise HTTPException(status_code=400, detail="子分類與分類不一致")

    product.current_name = current_name.strip()
    product.brand = brand.strip() or None
    product.model = model.strip() or None
    product.current_status = current_status.strip() or None
    product.current_price = current_price
    product.category_id = category_id
    product.subcategory_id = subcategory_id
    product.is_active = is_active
    session.commit()
    qs = urlencode({"message": "已儲存"})
    return RedirectResponse(url=f"/products/{product_id}?{qs}", status_code=303)


@router.post("/categories")
def create_category(name: str = Form(...), session: Session = Depends(get_session)):
    name = name.strip()
    if not name:
        raise HTTPException(status_code=400, detail="分類名稱不可為空")
    category = Category(name=name)
    session.add(category)
    try:
        session.flush()
    except IntegrityError:
        session.rollback()
        raise HTTPException(status_code=400, detail="分類名稱已存在")
    # 原價屋許多分類本身沒有第二層子分類，實際資料庫慣例是建一筆名稱為空
    # 字串的子分類代表「分類本身」，讓新分類一開始就有可用的子分類可選。
    subcategory = Subcategory(category_id=category.id, name="")
    session.add(subcategory)
    session.commit()
    return {
        "category_id": category.id,
        "category_label": category.label,
        "subcategory_id": subcategory.id,
        "subcategory_label": category.label,
    }


@router.get("/merge")
def merge_form(request: Request, message: str | None = None, error: str | None = None,
               session: Session = Depends(get_session)):
    # 批量合併一次最多可產生 100 組 MergeLog（similarity-hints 頁一次最多勾選
    # 100 組候選配對），這裡的上限要能容納這個實際上限，否則超出的紀錄永遠
    # 無法從這個未分頁列表被找到、被 Undo。
    logs = session.query(MergeLog).order_by(MergeLog.merged_at.desc()).limit(200).all()
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
