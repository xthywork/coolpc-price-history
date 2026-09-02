from __future__ import annotations
import datetime
from sqlalchemy import ForeignKey, UniqueConstraint
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship


class Base(DeclarativeBase):
    pass


class Category(Base):
    __tablename__ = "categories"
    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(unique=True)
    subcategories: Mapped[list["Subcategory"]] = relationship(back_populates="category")


class Subcategory(Base):
    __tablename__ = "subcategories"
    __table_args__ = (UniqueConstraint("category_id", "name"),)
    id: Mapped[int] = mapped_column(primary_key=True)
    category_id: Mapped[int] = mapped_column(ForeignKey("categories.id"))
    name: Mapped[str]
    category: Mapped["Category"] = relationship(back_populates="subcategories")


class Product(Base):
    __tablename__ = "products"
    id: Mapped[int] = mapped_column(primary_key=True)
    category_id: Mapped[int] = mapped_column(ForeignKey("categories.id"))
    subcategory_id: Mapped[int] = mapped_column(ForeignKey("subcategories.id"))
    current_name: Mapped[str] = mapped_column(index=True)
    brand: Mapped[str | None] = mapped_column(default=None)
    model: Mapped[str | None] = mapped_column(default=None)
    current_status: Mapped[str | None] = mapped_column(default=None)
    current_price: Mapped[int]
    # 上次價格異動幅度，於 Task 8 ingest_product 每次比對到既有商品時更新；
    # 新商品建立時為 None。用於 Task 17 搜尋條件「最近漲價/降價/漲跌幅」，
    # 避免每次搜尋都要對全表逐筆計算統計。
    last_change_amount: Mapped[int | None] = mapped_column(default=None)
    last_change_percent: Mapped[float | None] = mapped_column(default=None)
    is_active: Mapped[bool] = mapped_column(default=True)
    first_seen_at: Mapped[datetime.datetime]
    last_seen_at: Mapped[datetime.datetime]
    merged_into_id: Mapped[int | None] = mapped_column(ForeignKey("products.id"), default=None)
    created_at: Mapped[datetime.datetime]


class ProductName(Base):
    __tablename__ = "product_names"
    id: Mapped[int] = mapped_column(primary_key=True)
    product_id: Mapped[int] = mapped_column(ForeignKey("products.id"), index=True)
    name: Mapped[str] = mapped_column(index=True, unique=True)
    first_seen_at: Mapped[datetime.datetime]
    last_seen_at: Mapped[datetime.datetime]


class PriceHistory(Base):
    __tablename__ = "price_history"
    id: Mapped[int] = mapped_column(primary_key=True)
    product_id: Mapped[int] = mapped_column(ForeignKey("products.id"), index=True)
    price: Mapped[int]
    status: Mapped[str | None] = mapped_column(default=None)
    badges: Mapped[str | None] = mapped_column(default=None)
    scraped_at: Mapped[datetime.datetime] = mapped_column(index=True)
    snapshot_id: Mapped[int] = mapped_column(ForeignKey("scrape_snapshots.id"))


class ScrapeSnapshot(Base):
    __tablename__ = "scrape_snapshots"
    id: Mapped[int] = mapped_column(primary_key=True)
    fetched_at: Mapped[datetime.datetime]
    scrape_type: Mapped[str]
    raw_html_path: Mapped[str | None] = mapped_column(default=None)
    status: Mapped[str] = mapped_column(default="success")
    error_message: Mapped[str | None] = mapped_column(default=None)
    total_products: Mapped[int] = mapped_column(default=0)
    new_products: Mapped[int] = mapped_column(default=0)
    delisted_products: Mapped[int] = mapped_column(default=0)
    price_up_count: Mapped[int] = mapped_column(default=0)
    price_down_count: Mapped[int] = mapped_column(default=0)
    created_at: Mapped[datetime.datetime]


class MergeLog(Base):
    __tablename__ = "merge_log"
    id: Mapped[int] = mapped_column(primary_key=True)
    source_product_id: Mapped[int] = mapped_column(ForeignKey("products.id"))
    target_product_id: Mapped[int] = mapped_column(ForeignKey("products.id"))
    merged_at: Mapped[datetime.datetime]
    undone_at: Mapped[datetime.datetime | None] = mapped_column(default=None)
    # JSON 陣列，記錄本次合併時被改掛到 target 的 ProductName.id 清單，
    # 供 Task 15 的 undo_merge 精確還原（不能只靠時間或名稱反推）。
    moved_name_ids: Mapped[str] = mapped_column(default="[]")


class SimilarityHint(Base):
    __tablename__ = "similarity_hints"
    id: Mapped[int] = mapped_column(primary_key=True)
    product_a_id: Mapped[int] = mapped_column(ForeignKey("products.id"))
    product_b_id: Mapped[int] = mapped_column(ForeignKey("products.id"))
    score: Mapped[float]
    computed_at: Mapped[datetime.datetime]
    dismissed: Mapped[bool] = mapped_column(default=False)
