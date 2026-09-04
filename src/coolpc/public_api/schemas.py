from __future__ import annotations
import datetime
from pydantic import BaseModel


class CategoryOut(BaseModel):
    id: int
    name: str


class SubcategoryOut(BaseModel):
    id: int
    name: str
    category_id: int


class ProductListItem(BaseModel):
    id: int
    current_name: str
    category_name: str
    subcategory_name: str
    current_price: int
    previous_price: int | None
    change_amount: int | None
    change_percent: float | None
    low_30d: int | None
    high_30d: int | None
    is_active: bool
    last_seen_at: datetime.datetime


class ProductListPage(BaseModel):
    items: list[ProductListItem]
    total: int
    limit: int
    offset: int


class ProductStatsOut(BaseModel):
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


class ProductDetail(BaseModel):
    id: int
    current_name: str
    historical_names: list[str]
    category_name: str
    subcategory_name: str
    current_price: int
    previous_price: int | None
    change_amount: int | None
    change_percent: float | None
    created_at: datetime.datetime
    last_seen_at: datetime.datetime
    is_active: bool
    stats: ProductStatsOut


class PricePoint(BaseModel):
    scraped_at: datetime.datetime
    price: int


class CompareItem(BaseModel):
    id: int
    current_name: str
    current_price: int
    low_7d: int | None
    low_30d: int | None
    high_30d: int | None
    all_time_low: int
    all_time_high: int
    change_amount: int | None
    change_percent: float | None


class ComparePricePoint(BaseModel):
    product_id: int
    scraped_at: datetime.datetime
    price: int


class CompareResult(BaseModel):
    items: list[CompareItem]
    series: list[ComparePricePoint]
