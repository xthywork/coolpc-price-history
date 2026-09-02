from __future__ import annotations
from dataclasses import dataclass
from sqlalchemy.orm import Session
from coolpc.db.models import Product, ProductName


@dataclass
class SearchFilters:
    q: str | None = None
    category_id: int | None = None
    subcategory_id: int | None = None
    brand: str | None = None
    model: str | None = None
    min_price: int | None = None
    max_price: int | None = None
    is_active: bool | None = None
    recent_change: str | None = None  # "up" | "down" | None
    min_change_percent: float | None = None
    max_change_percent: float | None = None
    sort: str = "last_seen_desc"
    limit: int = 50
    offset: int = 0


_SORT_MAP = {
    "last_seen_desc": Product.last_seen_at.desc(),
    "price_asc": Product.current_price.asc(),
    "price_desc": Product.current_price.desc(),
    "name_asc": Product.current_name.asc(),
}


def search_products(session: Session, filters: SearchFilters) -> tuple[list[Product], int]:
    query = session.query(Product).filter(Product.merged_into_id.is_(None))

    if filters.q:
        matched_ids = [
            row[0] for row in
            session.query(ProductName.product_id)
            .filter(ProductName.name.like(f"%{filters.q}%"))
            .distinct()
            .all()
        ]
        if not matched_ids:
            return [], 0
        query = query.filter(Product.id.in_(matched_ids))

    if filters.category_id is not None:
        query = query.filter(Product.category_id == filters.category_id)
    if filters.subcategory_id is not None:
        query = query.filter(Product.subcategory_id == filters.subcategory_id)
    if filters.brand:
        query = query.filter(Product.brand == filters.brand)
    if filters.model:
        query = query.filter(Product.model.like(f"%{filters.model}%"))
    if filters.min_price is not None:
        query = query.filter(Product.current_price >= filters.min_price)
    if filters.max_price is not None:
        query = query.filter(Product.current_price <= filters.max_price)
    if filters.is_active is not None:
        query = query.filter(Product.is_active == filters.is_active)
    if filters.recent_change == "up":
        query = query.filter(Product.last_change_amount > 0)
    elif filters.recent_change == "down":
        query = query.filter(Product.last_change_amount < 0)
    if filters.min_change_percent is not None:
        query = query.filter(Product.last_change_percent >= filters.min_change_percent)
    if filters.max_change_percent is not None:
        query = query.filter(Product.last_change_percent <= filters.max_change_percent)

    total = query.count()
    query = query.order_by(_SORT_MAP.get(filters.sort, Product.last_seen_at.desc()))
    query = query.offset(filters.offset).limit(filters.limit)
    return query.all(), total
