from __future__ import annotations
import datetime as dt
from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session
from coolpc.public_api.dependencies import get_session
from coolpc.public_api import schemas
from coolpc.db.models import Category, Subcategory, Product, ProductName
from coolpc.search.service import SearchFilters, search_products
from coolpc.stats.service import compute_product_stats, get_price_history

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


@router.get("/products/{product_id}", response_model=schemas.ProductDetail)
def get_product(product_id: int, session: Session = Depends(get_session)):
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
    return schemas.ProductDetail(
        id=product.id, current_name=product.current_name, historical_names=names,
        category_name=category.name, subcategory_name=subcategory.name,
        current_price=product.current_price, previous_price=stats.previous_price,
        change_amount=stats.change_amount, change_percent=stats.change_percent,
        first_seen_at=product.first_seen_at, last_seen_at=product.last_seen_at,
        is_active=product.is_active,
        stats=schemas.ProductStatsOut(**stats.__dict__),
    )


@router.get("/products/{product_id}/prices", response_model=list[schemas.PricePoint])
def get_product_prices(
    product_id: int,
    start: dt.datetime | None = None,
    end: dt.datetime | None = None,
    days: int | None = None,
    session: Session = Depends(get_session),
):
    product = session.get(Product, product_id)
    if product is None or product.merged_into_id is not None:
        raise HTTPException(status_code=404, detail="商品不存在")
    effective_start = start
    if days is not None and start is None:
        effective_start = dt.datetime.utcnow() - dt.timedelta(days=days)
    history = get_price_history(session, product_id, start=effective_start, end=end)
    return [schemas.PricePoint(scraped_at=h.scraped_at, price=h.price) for h in history]


@router.get("/products/{product_id}/stats", response_model=schemas.ProductStatsOut)
def get_product_stats(product_id: int, session: Session = Depends(get_session)):
    product = session.get(Product, product_id)
    if product is None or product.merged_into_id is not None:
        raise HTTPException(status_code=404, detail="商品不存在")
    stats = compute_product_stats(session, product_id)
    return schemas.ProductStatsOut(**stats.__dict__)


@router.get("/compare", response_model=schemas.CompareResult)
def compare_products(ids: str, session: Session = Depends(get_session)):
    try:
        product_ids = [int(x) for x in ids.split(",") if x.strip()]
    except ValueError:
        raise HTTPException(status_code=400, detail="ids 格式錯誤，需為逗號分隔的整數")
    if not (2 <= len(product_ids) <= 5):
        raise HTTPException(status_code=400, detail="比較商品數量需介於 2 到 5 個之間")

    items: list[schemas.CompareItem] = []
    series: list[schemas.ComparePricePoint] = []
    for pid in product_ids:
        product = session.get(Product, pid)
        if product is None or product.merged_into_id is not None:
            raise HTTPException(status_code=404, detail=f"商品不存在: {pid}")
        stats = compute_product_stats(session, pid)
        items.append(schemas.CompareItem(
            id=product.id, current_name=product.current_name, current_price=product.current_price,
            low_7d=stats.low_7d, low_30d=stats.low_30d, high_30d=stats.high_30d,
            all_time_low=stats.all_time_low, all_time_high=stats.all_time_high,
            change_amount=stats.change_amount, change_percent=stats.change_percent,
        ))
        for h in get_price_history(session, pid):
            series.append(schemas.ComparePricePoint(product_id=pid, scraped_at=h.scraped_at, price=h.price))

    return schemas.CompareResult(items=items, series=series)
