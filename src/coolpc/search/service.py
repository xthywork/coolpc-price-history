from __future__ import annotations
from dataclasses import dataclass
from sqlalchemy import or_
from sqlalchemy.orm import Session
from coolpc.db.models import Category, Product, ProductName


@dataclass
class SearchFilters:
    q: str | None = None
    q_match: str = "and"  # "or" | "and" — 空白分隔的每個片段用 OR 還是 AND 語意比對
    category_id: int | None = None
    subcategory_id: int | None = None
    brand: str | None = None
    model: str | None = None
    min_price: int | None = None
    max_price: int | None = None
    is_active: bool | None = None
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
        tokens = filters.q.split()
        if filters.q_match == "and":
            # 每個空白分隔的片段都必須各自命中（不要求整段字串本身連續出現）
            # ——例如搜尋「ZOTAC 3050」要能找到「ZOTAC RTX3050 ECO SOLO」，
            # 即使商品名稱裡並沒有「ZOTAC 3050」這個連續子字串；但同時
            # 「ZOTAC GT730 2GB Zone Edition」因為完全不含「3050」，仍會被
            # 正確排除。這是預設語意，用於所有商品名稱搜尋（含公開搜尋頁）。
            query = _require_all_patterns(query, session, set(tokens))
        else:
            # OR 語意：任一片段命中即算符合，同時保留整段字串本身的比對
            # （名稱本來就含空白時，例如「RTX 5070」，仍要能整段比對到）。
            # 僅在明確要求較寬鬆的瀏覽/篩選情境下使用（非預設）。
            patterns = {filters.q, *tokens}
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


def search_products_and(session: Session, q: str, limit: int | None = None) -> list[Product]:
    """AND 語意搜尋：每個空白分隔的 token 都必須各自在該商品的某個歷史名稱
    （ProductName）上比對到才算符合——不必是同一列，同一商品底下的不同
    名稱列都算數；也不要求整段字串本身連續出現（見 search_products()
    q_match="and" 分支的說明）。用於名稱自動完成（例如管理後台合併頁、
    商品比較頁的加入搜尋）：比對範圍精確，不像單純 OR 語意會在大量真實
    資料下讓真正符合的商品被籠統結果和 LIMIT 擠出去。

    預設不限制筆數（limit=None）——AND 語意本身已經夠精確，使用者要看到
    所有真正符合條件的商品，不要因為人為的筆數上限而漏掉。
    """
    if not q or not q.strip():
        return []
    tokens = q.split()
    query = session.query(Product).filter(Product.merged_into_id.is_(None))
    query = _require_all_patterns(query, session, set(tokens))
    query = query.order_by(Product.last_seen_at.desc())
    if limit is not None:
        query = query.limit(limit)
    return query.all()
