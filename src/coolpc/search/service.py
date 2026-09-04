from __future__ import annotations
from dataclasses import dataclass
from sqlalchemy import or_
from sqlalchemy.orm import Session
from coolpc.db.models import Category, Product, ProductName


@dataclass
class SearchFilters:
    q: str | None = None
    q_match: str = "or"  # "or" | "and" — 空白分隔的每個片段用 OR 還是 AND 語意比對
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
    "brand_asc": Product.brand.asc().nulls_last(),
    "status_active_first": Product.is_active.desc(),
}


def _require_all_patterns(query, session: Session, patterns: set[str]):
    """把 query 限縮成：每個 pattern 都必須各自在該商品的某個歷史名稱
    （ProductName）上比對到才算符合——不必是同一列，同一商品底下的不同
    名稱列都算數。是 search_products() 的 q_match="and" 與
    search_products_and() 共用的核心邏輯。"""
    for pattern in patterns:
        matched_ids = (
            session.query(ProductName.product_id)
            .filter(ProductName.name.like(f"%{pattern}%"))
            .distinct()
        )
        query = query.filter(Product.id.in_(matched_ids))
    return query


def search_products(session: Session, filters: SearchFilters) -> tuple[list[Product], int]:
    query = session.query(Product).filter(Product.merged_into_id.is_(None))

    if filters.q:
        # 空白分隔的每個片段，同時保留整段字串本身的比對
        # （名稱本來就含空白時，例如「RTX 5070」，仍要能整段比對到）。
        tokens = filters.q.split()
        patterns = {filters.q, *tokens}
        if filters.q_match == "and":
            # 每個片段都必須同時命中，用於需要精確鎖定單一商品的場景
            # （例如後台商品搜尋、商品比較的名稱自動完成）。
            query = _require_all_patterns(query, session, patterns)
        else:
            matched_ids = [
                row[0] for row in
                session.query(ProductName.product_id)
                .filter(or_(*[ProductName.name.like(f"%{p}%") for p in patterns]))
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
    if filters.sort == "category_asc":
        # 依分類的自訂顯示順序排序（見 Category.sort_order），跟分類下拉
        # 選單的順序一致，而不是依原價屋原始分類名稱的字母順序。
        query = (
            query.join(Category, Product.category_id == Category.id)
            .order_by(Category.sort_order.asc().nulls_last(), Category.name.asc())
        )
    else:
        query = query.order_by(_SORT_MAP.get(filters.sort, Product.last_seen_at.desc()))
    query = query.offset(filters.offset).limit(filters.limit)
    return query.all(), total


def search_products_and(session: Session, q: str, limit: int = 10) -> list[Product]:
    """AND 語意搜尋：每個空白分隔的 token（以及整段字串本身）都必須各自在該商品的
    某個歷史名稱（ProductName）上比對到才算符合——不必是同一列，同一商品底下的
    不同名稱列都算數。用於管理後台合併頁的名稱自動完成：比對範圍精確，
    不像 search_products() 的 OR 語意會在大量真實資料下讓真正符合的商品被
    LIMIT 擠出結果（那個 OR 語意本身是刻意保留、給公開搜尋頁用的，這裡不動它）。
    """
    if not q or not q.strip():
        return []
    tokens = q.split()
    patterns = {q, *tokens}
    query = session.query(Product).filter(Product.merged_into_id.is_(None))
    query = _require_all_patterns(query, session, patterns)
    query = query.order_by(Product.last_seen_at.desc()).limit(limit)
    return query.all()
