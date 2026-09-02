from __future__ import annotations
import datetime
from dataclasses import dataclass
from sqlalchemy import func
from sqlalchemy.orm import Session
from coolpc.db.models import Product, PriceHistory


@dataclass
class ProductStats:
    current_price: int
    previous_price: int | None
    change_amount: int | None
    change_percent: float | None
    low_7d: int | None
    high_7d: int | None
    low_30d: int | None
    high_30d: int | None
    low_90d: int | None
    high_90d: int | None
    all_time_low: int
    all_time_high: int


def get_merged_group_product_ids(session: Session, product_id: int) -> list[int]:
    source_ids = [
        row[0] for row in
        session.query(Product.id).filter(Product.merged_into_id == product_id).all()
    ]
    return [product_id, *source_ids]


def get_price_history(
    session: Session, product_id: int,
    start: datetime.datetime | None = None, end: datetime.datetime | None = None,
) -> list[PriceHistory]:
    group_ids = get_merged_group_product_ids(session, product_id)
    query = session.query(PriceHistory).filter(PriceHistory.product_id.in_(group_ids))
    if start is not None:
        query = query.filter(PriceHistory.scraped_at >= start)
    if end is not None:
        query = query.filter(PriceHistory.scraped_at <= end)
    return query.order_by(PriceHistory.scraped_at.asc()).all()


def _min_max(session: Session, group_ids: list[int],
             since: datetime.datetime | None) -> tuple[int | None, int | None]:
    query = session.query(func.min(PriceHistory.price), func.max(PriceHistory.price)).filter(
        PriceHistory.product_id.in_(group_ids)
    )
    if since is not None:
        query = query.filter(PriceHistory.scraped_at >= since)
    return query.one()


def compute_product_stats(session: Session, product_id: int,
                           now: datetime.datetime | None = None) -> ProductStats:
    product = session.get(Product, product_id)
    if product is None:
        raise ValueError(f"商品不存在: {product_id}")
    now = now or datetime.datetime.utcnow()
    group_ids = get_merged_group_product_ids(session, product_id)

    recent = (
        session.query(PriceHistory)
        .filter(PriceHistory.product_id.in_(group_ids))
        .order_by(PriceHistory.scraped_at.desc())
        .limit(2)
        .all()
    )
    previous_price = recent[1].price if len(recent) > 1 else None
    change_amount = None
    change_percent = None
    if previous_price is not None:
        change_amount = product.current_price - previous_price
        change_percent = (change_amount / previous_price * 100) if previous_price else None

    low_7d, high_7d = _min_max(session, group_ids, now - datetime.timedelta(days=7))
    low_30d, high_30d = _min_max(session, group_ids, now - datetime.timedelta(days=30))
    low_90d, high_90d = _min_max(session, group_ids, now - datetime.timedelta(days=90))
    all_time_low, all_time_high = _min_max(session, group_ids, None)

    return ProductStats(
        current_price=product.current_price, previous_price=previous_price,
        change_amount=change_amount, change_percent=change_percent,
        low_7d=low_7d, high_7d=high_7d, low_30d=low_30d, high_30d=high_30d,
        low_90d=low_90d, high_90d=high_90d,
        all_time_low=all_time_low if all_time_low is not None else product.current_price,
        all_time_high=all_time_high if all_time_high is not None else product.current_price,
    )
