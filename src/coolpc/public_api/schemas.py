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
