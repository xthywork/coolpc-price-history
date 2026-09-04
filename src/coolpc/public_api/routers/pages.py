from __future__ import annotations
from pathlib import Path
from urllib.parse import urlencode
from fastapi import APIRouter, Depends, Request
from fastapi.templating import Jinja2Templates
from sqlalchemy import func
from sqlalchemy.orm import Session
from coolpc.public_api.dependencies import get_session, get_visible_product, _is_visible
from coolpc.query_types import OptionalInt, OptionalFloat, OptionalBool
from coolpc.db.models import Category, Subcategory, Product, ProductName
from coolpc.search.service import SearchFilters, search_products
from coolpc.stats.service import compute_product_stats, get_price_history

router = APIRouter()
templates = Jinja2Templates(directory=str(Path(__file__).parent.parent / "templates"))

PAGE_SIZE = 30
COMPARE_COLORS = ["#2563eb", "#dc2626", "#16a34a", "#d97706", "#7c3aed"]


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
    recent_change: str | None = None,
    min_change_percent: OptionalFloat = None,
    max_change_percent: OptionalFloat = None,
    sort: str = "last_seen_desc",
    page: int = 1,
    session: Session = Depends(get_session),
):
    page = max(page, 1)
    filters = SearchFilters(
        q=q, category_id=category_id, subcategory_id=subcategory_id, brand=brand, model=model,
        min_price=min_price, max_price=max_price, is_active=is_active,
        recent_change=recent_change, min_change_percent=min_change_percent,
        max_change_percent=max_change_percent,
        sort=sort, limit=PAGE_SIZE, offset=(page - 1) * PAGE_SIZE,
    )
    products, total = search_products(session, filters)

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
        "recent_change": recent_change, "min_change_percent": min_change_percent,
        "max_change_percent": max_change_percent, "sort": sort,
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
            "recent_change": recent_change, "min_change_percent": min_change_percent,
            "max_change_percent": max_change_percent, "sort": sort,
        },
        "query_string": urlencode(query_params),
        "page": page, "total_pages": max((total + PAGE_SIZE - 1) // PAGE_SIZE, 1), "total": total,
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
        "items": items, "ids": ids or "", "error": error, "colors": COMPARE_COLORS,
    })
