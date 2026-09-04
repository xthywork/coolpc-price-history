from __future__ import annotations
from pathlib import Path
from urllib.parse import urlencode
from fastapi import APIRouter, Depends, Request
from fastapi.templating import Jinja2Templates
from sqlalchemy import func
from sqlalchemy.orm import Session
from coolpc.public_api.dependencies import get_session, get_visible_product, _is_visible
from coolpc.query_types import OptionalInt, OptionalBool
from coolpc.db.models import Category, Subcategory, Product, ProductName
from coolpc.search.service import SearchFilters, search_products
from coolpc.stats.service import compute_product_stats, get_price_history

router = APIRouter()
templates = Jinja2Templates(directory=str(Path(__file__).parent.parent / "templates"))

PAGE_SIZE_OPTIONS = [10, 20, 50, 100, 500, 1000]
DEFAULT_PAGE_SIZE = 20
# 「全部」選項不真的省略 LIMIT（search_products 目前一律會套用 limit），
# 而是用一個遠超過實際商品總數的大數字模擬「不分頁」，不需要改動共用的
# search_products() 邏輯。
_ALL_PAGE_SIZE_LIMIT = 100_000
COMPARE_COLORS = ["#2563eb", "#dc2626", "#16a34a", "#d97706", "#7c3aed"]


def _resolve_page_size(page_size: str) -> tuple[str, int]:
    """回傳 (正規化後的 page_size 字串, 實際查詢用的 limit)。"""
    if page_size == "all":
        return "all", _ALL_PAGE_SIZE_LIMIT
    if page_size.isdigit() and int(page_size) in PAGE_SIZE_OPTIONS:
        return page_size, int(page_size)
    return str(DEFAULT_PAGE_SIZE), DEFAULT_PAGE_SIZE


def _build_page_list(current: int, total_pages: int) -> list[int | None]:
    """回傳分頁列要顯示的頁碼清單；None 代表省略號（…）。固定顯示第一頁、
    最後一頁，以及目前頁碼前後兩頁，中間有斷層就插入一個 None。"""
    if total_pages <= 7:
        return list(range(1, total_pages + 1))
    pages: list[int | None] = [1]
    window_start = max(2, current - 2)
    window_end = min(total_pages - 1, current + 2)
    if window_start > 2:
        pages.append(None)
    pages.extend(range(window_start, window_end + 1))
    if window_end < total_pages - 1:
        pages.append(None)
    pages.append(total_pages)
    return pages


@router.get("/")
def search_page(
    request: Request,
    q: str | None = None,
    category_id: OptionalInt = None,
    subcategory_id: OptionalInt = None,
    brand: str | None = None,
    model: str | None = None,
    min_price: OptionalInt = None,
    max_price: OptionalInt = None,
    is_active: OptionalBool = None,
    sort: str = "price_asc",
    page: int = 1,
    page_size: str = str(DEFAULT_PAGE_SIZE),
    session: Session = Depends(get_session),
):
    page = max(page, 1)
    page_size, effective_page_size = _resolve_page_size(page_size)
    filters = SearchFilters(
        q=q, category_id=category_id, subcategory_id=subcategory_id, brand=brand, model=model,
        min_price=min_price, max_price=max_price, is_active=is_active,
        sort=sort, limit=effective_page_size, offset=(page - 1) * effective_page_size,
    )
    products, total = search_products(session, filters)
    total_pages = max((total + effective_page_size - 1) // effective_page_size, 1)

    last_updated_query = session.query(func.max(Product.last_seen_at)).filter(Product.merged_into_id.is_(None))
    if filters.subcategory_id is not None:
        last_updated_query = last_updated_query.filter(Product.subcategory_id == filters.subcategory_id)
    if filters.is_active is not None:
        last_updated_query = last_updated_query.filter(Product.is_active == filters.is_active)
    last_updated = last_updated_query.scalar()

    rows = []
    for p in products:
        rows.append({
            "product": p,
            "category": session.get(Category, p.category_id),
        })

    query_params = {k: v for k, v in {
        "q": q, "category_id": category_id, "subcategory_id": subcategory_id,
        "brand": brand, "model": model,
        "min_price": min_price, "max_price": max_price, "is_active": is_active,
        "sort": sort, "page_size": page_size,
    }.items() if v not in (None, "")}

    subcategory_rows = (
        session.query(Subcategory, Category)
        .join(Category, Subcategory.category_id == Category.id)
        .order_by(Category.sort_order.asc().nulls_last(), Category.name, Subcategory.name)
        .all()
    )
    subcategories = [
        # 原價屋許多分類本身沒有第二層子分類，實際資料庫裡是一筆名稱為空字串
        # 的子分類；這種情況只顯示分類名稱，不要留下一個沒有內容的「 / 」。
        {"id": sc.id, "label": f"{cat.label} / {sc.label}" if sc.label else cat.label}
        for sc, cat in subcategory_rows
    ]

    brands = [
        row[0] for row in
        session.query(Product.brand).filter(Product.brand.isnot(None)).distinct()
        .order_by(Product.brand).all()
    ]

    return templates.TemplateResponse(request, "search.html", {
        "rows": rows,
        "categories": session.query(Category).order_by(Category.sort_order.asc().nulls_last(), Category.name).all(),
        "subcategories": subcategories,
        "brands": brands,
        "query": {
            "q": q or "", "category_id": category_id, "subcategory_id": subcategory_id,
            "brand": brand, "model": model,
            "min_price": min_price, "max_price": max_price, "is_active": is_active,
            "sort": sort, "page_size": page_size,
        },
        "query_string": urlencode(query_params),
        "page": page,
        "total_pages": total_pages,
        "page_list": _build_page_list(page, total_pages),
        "page_size_options": PAGE_SIZE_OPTIONS,
        "total": total,
        "last_updated": last_updated,
    })


@router.get("/products/{product_id}")
def product_detail_page(
    request: Request,
    product: Product = Depends(get_visible_product),
    session: Session = Depends(get_session),
):
    category = session.get(Category, product.category_id)
    subcategory = session.get(Subcategory, product.subcategory_id)
    stats = compute_product_stats(session, product.id)
    names = [
        n.name for n in
        session.query(ProductName).filter_by(product_id=product.id)
        .order_by(ProductName.first_seen_at).all()
    ]
    history = list(reversed(get_price_history(session, product.id)))
    return templates.TemplateResponse(request, "product_detail.html", {
        "product": product, "category": category, "subcategory": subcategory,
        "stats": stats, "historical_names": names, "history": history,
    })


@router.get("/compare")
def compare_page(request: Request, ids: str | None = None, session: Session = Depends(get_session)):
    items = []
    error = None
    if ids:
        try:
            product_ids = [int(x) for x in ids.split(",") if x.strip()]
        except ValueError:
            product_ids = []
            error = "ids 格式錯誤，請輸入逗號分隔的商品 ID"
        if error is None and not (2 <= len(product_ids) <= 5):
            error = "請選擇 2 到 5 個商品進行比較"
        if error is None:
            for pid in product_ids:
                product = session.get(Product, pid)
                if not _is_visible(product):
                    error = f"商品不存在: {pid}"
                    items = []
                    break
                items.append({"product": product, "stats": compute_product_stats(session, pid)})

    return templates.TemplateResponse(request, "compare.html", {
        "items": items, "ids": ids or "",
        "error": error, "colors": COMPARE_COLORS,
    })
