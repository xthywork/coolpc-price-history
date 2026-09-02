import datetime
from sqlalchemy import create_engine
from sqlalchemy.orm import Session
from coolpc.db.models import Base, Product, ProductName, PriceHistory
from coolpc.ingest.service import (
    get_or_create_category, get_or_create_subcategory, ingest_product,
    guess_brand, guess_model,
)
from coolpc.parser.models import ParsedProduct

def _session():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    return Session(engine)

def test_ingest_new_product_creates_all_records():
    session = _session()
    t0 = datetime.datetime(2026, 2, 1, 21, 40)
    cat = get_or_create_category(session, "顯示卡VGA")
    sub = get_or_create_subcategory(session, cat, "NVIDIA")
    parsed = ParsedProduct(category_name="顯示卡VGA", subcategory_name="NVIDIA",
                            name="ASUS DUAL-RTX3050-O6G", price=7990, status=None, badges="◆ ★")
    product, is_new, delta = ingest_product(session, parsed, cat, sub, t0, snapshot_id=1)
    session.flush()

    assert is_new is True
    assert delta == 0
    assert product.current_price == 7990
    assert session.query(ProductName).filter_by(name="ASUS DUAL-RTX3050-O6G").count() == 1
    assert session.query(PriceHistory).filter_by(product_id=product.id).count() == 1

def test_ingest_existing_product_updates_price_and_reactivates():
    session = _session()
    t0 = datetime.datetime(2026, 2, 1, 21, 40)
    t1 = datetime.datetime(2026, 2, 2, 0, 0)
    cat = get_or_create_category(session, "顯示卡VGA")
    sub = get_or_create_subcategory(session, cat, "NVIDIA")
    parsed = ParsedProduct(category_name="顯示卡VGA", subcategory_name="NVIDIA",
                            name="ASUS DUAL-RTX3050-O6G", price=7990, status=None, badges="◆ ★")
    product, _, _ = ingest_product(session, parsed, cat, sub, t0, snapshot_id=1)
    session.flush()
    product.is_active = False  # 模擬曾經下架

    parsed2 = ParsedProduct(category_name="顯示卡VGA", subcategory_name="NVIDIA",
                             name="ASUS DUAL-RTX3050-O6G", price=8490, status=None, badges="◆ ★ 熱賣")
    product2, is_new2, delta2 = ingest_product(session, parsed2, cat, sub, t1, snapshot_id=2)
    session.flush()

    assert is_new2 is False
    assert product2.id == product.id
    assert delta2 == 500
    assert product2.current_price == 8490
    assert product2.is_active is True
    assert product2.last_seen_at == t1
    assert product2.last_change_amount == 500
    assert round(product2.last_change_percent, 2) == round(500 / 7990 * 100, 2)
    assert session.query(ProductName).count() == 1  # 沒有新增歷史名稱
    assert session.query(PriceHistory).filter_by(product_id=product.id).count() == 2

def test_guess_brand_matches_known_prefix():
    assert guess_brand("ASUS DUAL-RTX3050-O6G") == "ASUS"
    assert guess_brand("微星 N730-2GD3V3") == "微星"
    assert guess_brand("不知名品牌的東西") is None

def test_guess_model_extracts_bracket_code():
    assert guess_model("ASUS【H-V500MV-31315U042W】i3-1315U") == "H-V500MV-31315U042W"
    assert guess_model("沒有型號代碼的商品") is None
