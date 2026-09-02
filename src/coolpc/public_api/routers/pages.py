from __future__ import annotations
from pathlib import Path
from urllib.parse import urlencode
from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.templating import Jinja2Templates
from sqlalchemy.orm import Session
from coolpc.public_api.dependencies import get_session
from coolpc.db.models import Category, Subcategory, Product, ProductName
from coolpc.search.service import SearchFilters, search_products
from coolpc.stats.service import compute_product_stats, get_price_history

router = APIRouter()
templates = Jinja2Templates(directory=str(Path(__file__).parent.parent / "templates"))

PAGE_SIZE = 30


@router.get("/")
def search_page(
    request: Request,
    q: str | None = None,
    category_id: int | None = None,
    subcategory_id: int | None = None,
    brand: str | None = None,
    model: str | None = None,
    min_price: int | None = None,
    max_price: int | None = None,
    is_active: bool | None = None,
    recent_change: str | None = None,
    min_change_percent: float | None = None,
    max_change_percent: float | None = None,
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

    rows = []
    for p in products:
        rows.append({
            "product": p,
            "category": session.get(Category, p.category_id),
            "stats": compute_product_stats(session, p.id),
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
        .order_by(Category.name, Subcategory.name)
        .all()
    )
    subcategories = [
        {"id": sc.id, "label": f"{cat.name} / {sc.name}"}
        for sc, cat in subcategory_rows
    ]

    return templates.TemplateResponse(request, "search.html", {
        "rows": rows,
        "categories": session.query(Category).order_by(Category.name).all(),
        "subcategories": subcategories,
        "query": {
            "q": q or "", "category_id": category_id, "subcategory_id": subcategory_id,
            "brand": brand, "model": model,
            "min_price": min_price, "max_price": max_price, "is_active": is_active,
            "recent_change": recent_change, "min_change_percent": min_change_percent,
            "max_change_percent": max_change_percent, "sort": sort,
        },
        "query_string": urlencode(query_params),
        "page": page, "total_pages": max((total + PAGE_SIZE - 1) // PAGE_SIZE, 1), "total": total,
    })


@router.get("/products/{product_id}")
def product_detail_page(request: Request, product_id: int, session: Session = Depends(get_session)):
    product = session.get(Product, product_id)
    if product is None or product.merged_into_id is not None:
        raise HTTPException(status_code=404, detail="商品不存在")
    category = session.get(Category, product.category_id)
    subcategory = session.get(Subcategory, product.subcategory_id)
    stats = compute_product_stats(session, product.id)
    names = [
        n.name for n in
        session.query(ProductName).filter_by(product_id=product.id)
        .order_by(ProductName.first_seen_at).all()
    ]
    history = list(reversed(get_price_history(session, product.id)))
    same_category = (
        session.query(Product)
        .filter(Product.category_id == product.category_id, Product.id != product.id,
                Product.merged_into_id.is_(None))
        .order_by(Product.last_seen_at.desc())
        .limit(20)
        .all()
    )
    return templates.TemplateResponse(request, "product_detail.html", {
        "product": product, "category": category, "subcategory": subcategory,
        "stats": stats, "historical_names": names, "history": history,
        "same_category_products": same_category,
    })
