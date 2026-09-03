from __future__ import annotations
import datetime
import re
from sqlalchemy.orm import Session
from coolpc.db.models import Category, Subcategory, Product, ProductName, PriceHistory, ScrapeSnapshot
from coolpc.parser.models import ParsedProduct, ParsedSnapshot

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


def ingest_snapshot(
    session: Session,
    parsed: ParsedSnapshot,
    scrape_type: str,
    raw_html_path: str | None,
) -> ScrapeSnapshot:
    # C3: fetched_at 來自 HTML 內嵌的時間戳，不是牆上時鐘時間。重複匯入同一份
    # 歷史檔案（或 import-dir 匯入到與先前重疊的日期範圍，README 記載的常見
    # 補匯流程）會用同一個 fetched_at 再次呼叫本函式；若不做防重，會為每個
    # 商品重複建立 PriceHistory，悄悄地把所有價格圖表、previous_price/
    # change_amount 統計都弄成兩倍。這裡做成 idempotent no-op：已有成功匯入
    # 紀錄就直接回傳既有的 ScrapeSnapshot，不重新處理。
    existing = (
        session.query(ScrapeSnapshot)
        .filter_by(fetched_at=parsed.fetched_at, status="success")
        .one_or_none()
    )
    if existing is not None:
        return existing

    # I6: 在建立本次快照之前，先找出「上一筆成功或部分成功」的快照，用它的
    # total_products 當作基準，判斷本次快照是否疑似「只解析到一部分」
    # （例如原站 HTML 結構局部改版，某些 <select> 區塊解析失敗）。
    prior_successful = (
        session.query(ScrapeSnapshot)
        .filter(ScrapeSnapshot.status.in_(["success", "partial"]))
        .order_by(ScrapeSnapshot.fetched_at.desc())
        .first()
    )

    snapshot = ScrapeSnapshot(
        fetched_at=parsed.fetched_at, scrape_type=scrape_type,
        raw_html_path=raw_html_path, status="success", error_message=None,
        created_at=datetime.datetime.utcnow(),
    )
    session.add(snapshot)
    session.flush()

    total = new = up = down = 0
    seen_product_ids: set[int] = set()

    for parsed_product in parsed.products:
        category = get_or_create_category(session, parsed_product.category_name)
        subcategory = get_or_create_subcategory(session, category, parsed_product.subcategory_name)
        product, is_new, price_delta = ingest_product(
            session, parsed_product, category, subcategory, parsed.fetched_at, snapshot.id,
        )
        seen_product_ids.add(product.id)
        total += 1
        if is_new:
            new += 1
        elif price_delta > 0:
            up += 1
        elif price_delta < 0:
            down += 1

    # I6: 本次快照商品數若遠低於前一次成功快照（低於 70%），視為解析可能不完整，
    # 標記為 partial 並且完全跳過下架比對——寧可暫時保留現有的 is_active 狀態不變，
    # 也不要因為一次可能有問題的解析而誤將大量商品下架。
    is_partial = (
        prior_successful is not None
        and prior_successful.total_products > 0
        and total < prior_successful.total_products * 0.7
    )

    delisted = 0
    if not is_partial:
        active_products = (
            session.query(Product)
            .filter(Product.is_active.is_(True), Product.merged_into_id.is_(None))
            .all()
        )
        for product in active_products:
            if product.id not in seen_product_ids:
                product.is_active = False
                delisted += 1

    snapshot.status = "partial" if is_partial else "success"
    snapshot.total_products = total
    snapshot.new_products = new
    snapshot.delisted_products = delisted
    snapshot.price_up_count = up
    snapshot.price_down_count = down
    return snapshot
