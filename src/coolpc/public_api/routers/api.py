from __future__ import annotations
from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session
from coolpc.public_api.dependencies import get_session
from coolpc.public_api import schemas
from coolpc.db.models import Category, Subcategory, Product
from coolpc.search.service import SearchFilters, search_products
from coolpc.stats.service import compute_product_stats

router = APIRouter(prefix="/api")


@router.get("/categories", response_model=list[schemas.CategoryOut])
def list_categories(session: Session = Depends(get_session)):
    categories = session.query(Category).order_by(Category.id).all()
    return [schemas.CategoryOut(id=c.id, name=c.name) for c in categories]


def _to_list_item(session: Session, product: Product) -> schemas.ProductListItem:
    category = session.get(Category, product.category_id)
    subcategory = session.get(Subcategory, product.subcategory_id)
    stats = compute_product_stats(session, product.id)
    return schemas.ProductListItem(
        id=product.id, current_name=product.current_name,
        category_name=category.name, subcategory_name=subcategory.name,
        current_price=product.current_price, previous_price=stats.previous_price,
        change_amount=stats.change_amount, change_percent=stats.change_percent,
        low_30d=stats.low_30d, high_30d=stats.high_30d,
        is_active=product.is_active, last_seen_at=product.last_seen_at,
    )


@router.get("/products", response_model=schemas.ProductListPage)
def list_products(
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
    limit: int = Query(default=50, le=200),
    offset: int = 0,
    session: Session = Depends(get_session),
):
    filters = SearchFilters(
        q=q, category_id=category_id, subcategory_id=subcategory_id, brand=brand, model=model,
        min_price=min_price, max_price=max_price, is_active=is_active,
        recent_change=recent_change, min_change_percent=min_change_percent,
        max_change_percent=max_change_percent, sort=sort, limit=limit, offset=offset,
    )
    products, total = search_products(session, filters)
    items = [_to_list_item(session, p) for p in products]
    return schemas.ProductListPage(items=items, total=total, limit=limit, offset=offset)
