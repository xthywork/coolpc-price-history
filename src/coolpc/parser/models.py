from __future__ import annotations
import datetime
from dataclasses import dataclass, field


class ParseError(Exception):
    """HTML 結構異常或無法解析時拋出。"""


@dataclass
class ParsedProduct:
    category_name: str
    subcategory_name: str
    name: str
    price: int
    status: str | None
    badges: str


@dataclass
class ParsedSnapshot:
    fetched_at: datetime.datetime
    products: list[ParsedProduct] = field(default_factory=list)
