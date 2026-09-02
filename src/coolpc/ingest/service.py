from __future__ import annotations
import datetime
import re
from sqlalchemy.orm import Session
from coolpc.db.models import Category, Subcategory, Product, ProductName, PriceHistory
from coolpc.parser.models import ParsedProduct

KNOWN_BRANDS = [
    "ASUS", "華碩", "微星", "MSI", "技嘉", "GIGABYTE", "酷碼", "ZOTAC", "INNO3D",
    "華擎", "ASRock", "INTEL", "NVIDIA", "Acer", "宏碁", "Lenovo", "聯想",
    "Synology", "HP", "AMD", "Kingston", "金士頓", "十銓", "威剛", "ADATA",
    "創見", "Transcend", "Seagate", "希捷", "WD", "威健", "Cooler Master",
]
MODEL_BRACKET_PATTERN = re.compile(r"[【｛]([A-Za-z0-9][A-Za-z0-9\-/. ]{2,})[】｝]")


def get_or_create_category(session: Session, name: str) -> Category:
    cat = session.query(Category).filter_by(name=name).one_or_none()
    if cat is None:
        cat = Category(name=name)
        session.add(cat)
        session.flush()
    return cat


def get_or_create_subcategory(session: Session, category: Category, name: str) -> Subcategory:
    sub = session.query(Subcategory).filter_by(category_id=category.id, name=name).one_or_none()
    if sub is None:
        sub = Subcategory(category_id=category.id, name=name)
        session.add(sub)
        session.flush()
    return sub


def guess_brand(name: str) -> str | None:
    for brand in KNOWN_BRANDS:
        if name.startswith(brand):
            return brand
    return None


def guess_model(name: str) -> str | None:
    m = MODEL_BRACKET_PATTERN.search(name)
    return m.group(1).strip() if m else None


def ingest_product(
    session: Session,
    parsed: ParsedProduct,
    category: Category,
    subcategory: Subcategory,
    fetched_at: datetime.datetime,
    snapshot_id: int,
) -> tuple[Product, bool, int]:
    existing_name = session.query(ProductName).filter_by(name=parsed.name).one_or_none()

    if existing_name is not None:
        product = session.get(Product, existing_name.product_id)
        price_delta = parsed.price - product.current_price
        product.last_change_amount = price_delta
        product.last_change_percent = (
            (price_delta / product.current_price * 100) if product.current_price else None
        )
        product.current_price = parsed.price
        product.current_status = parsed.status
        product.category_id = category.id
        product.subcategory_id = subcategory.id
        product.is_active = True
        product.last_seen_at = fetched_at
        existing_name.last_seen_at = fetched_at
        session.add(PriceHistory(
            product_id=product.id, price=parsed.price, status=parsed.status,
            badges=parsed.badges, scraped_at=fetched_at, snapshot_id=snapshot_id,
        ))
        return product, False, price_delta

    product = Product(
        category_id=category.id, subcategory_id=subcategory.id,
        current_name=parsed.name, brand=guess_brand(parsed.name), model=guess_model(parsed.name),
        current_status=parsed.status, current_price=parsed.price,
        is_active=True, first_seen_at=fetched_at, last_seen_at=fetched_at,
        created_at=fetched_at,
    )
    session.add(product)
    session.flush()
    session.add(ProductName(product_id=product.id, name=parsed.name,
                             first_seen_at=fetched_at, last_seen_at=fetched_at))
    session.add(PriceHistory(
        product_id=product.id, price=parsed.price, status=parsed.status,
        badges=parsed.badges, scraped_at=fetched_at, snapshot_id=snapshot_id,
    ))
    return product, True, 0
