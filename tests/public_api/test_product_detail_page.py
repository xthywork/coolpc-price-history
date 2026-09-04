import datetime
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, text
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool
from coolpc.db.models import Base, Category, Subcategory, Product, ProductName, PriceHistory, ScrapeSnapshot
from coolpc.public_api.app import app
from coolpc.public_api.dependencies import get_session


def _make_client():
    engine = create_engine(
        "sqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    TestingSession = sessionmaker(bind=engine)

    def override_get_session():
        session = TestingSession()
        try:
            yield session
        finally:
            session.close()

    app.dependency_overrides[get_session] = override_get_session
    return TestClient(app), TestingSession


def test_product_detail_page_renders_history_and_chart():
    client, Session_ = _make_client()
    t0 = datetime.datetime(2026, 2, 1)
    t1 = datetime.datetime(2026, 2, 2)
    with Session_() as session:
        cat = Category(name="顯示卡VGA")
        sub = Subcategory(name="NVIDIA", category=cat)
        session.add_all([cat, sub])
        session.flush()
        p = Product(category_id=cat.id, subcategory_id=sub.id, current_name="ASUS RTX 5070 v2",
                    current_price=19990, is_active=True, last_seen_at=t1, created_at=t0)
        session.add(p)
        session.flush()
        session.add_all([
            ProductName(product_id=p.id, name="ASUS RTX 5070", first_seen_at=t0, last_seen_at=t0),
            ProductName(product_id=p.id, name="ASUS RTX 5070 v2", first_seen_at=t1, last_seen_at=t1),
        ])
        session.add_all([
            PriceHistory(product_id=p.id, price=18990, status=None, badges="", scraped_at=t0, snapshot_id=1),
            PriceHistory(product_id=p.id, price=19990, status=None, badges="", scraped_at=t1, snapshot_id=2),
        ])
        session.commit()
        pid = p.id

    resp = client.get(f"/products/{pid}")
    assert resp.status_code == 200
    assert "ASUS RTX 5070 v2" in resp.text
    assert "ASUS RTX 5070" in resp.text  # 舊名稱要顯示
    assert 'id="priceChart"' in resp.text
    assert "/static/js/vendor/chart.umd.min.js" in resp.text
    assert "18,990" in resp.text  # 歷史價格列表出現舊價格


def test_product_detail_page_hides_trailing_slash_when_subcategory_name_is_blank():
    client, Session_ = _make_client()
    t = datetime.datetime(2026, 2, 1)
    with Session_() as session:
        cat = Category(name="無子分類測試分類")
        sub = Subcategory(name="", category=cat)
        session.add_all([cat, sub])
        session.flush()
        p = Product(category_id=cat.id, subcategory_id=sub.id, current_name="無子分類測試商品",
                    current_price=1000, is_active=True, last_seen_at=t, created_at=t)
        session.add(p)
        session.flush()
        session.add(ProductName(product_id=p.id, name=p.current_name, first_seen_at=t, last_seen_at=t))
        session.commit()
        pid = p.id

    resp = client.get(f"/products/{pid}")
    assert resp.status_code == 200
    assert "<span>無子分類測試分類</span>" in resp.text
    assert "無子分類測試分類 / " not in resp.text


def test_product_detail_page_404_for_missing():
    client, _ = _make_client()
    resp = client.get("/products/999")
    assert resp.status_code == 404


def test_product_detail_page_404_for_merged_away_product():
    client, Session_ = _make_client()
    t = datetime.datetime(2026, 2, 1)
    with Session_() as session:
        cat = Category(name="顯示卡VGA")
        sub = Subcategory(name="NVIDIA", category=cat)
        session.add_all([cat, sub])
        session.flush()
        target = Product(category_id=cat.id, subcategory_id=sub.id, current_name="目標商品",
                          current_price=1000, is_active=True, last_seen_at=t, created_at=t)
        session.add(target)
        session.flush()
        source = Product(category_id=cat.id, subcategory_id=sub.id, current_name="來源商品",
                          current_price=1000, is_active=False, last_seen_at=t,
                          created_at=t, merged_into_id=target.id)
        session.add(source)
        session.commit()
        source_id = source.id

    resp = client.get(f"/products/{source_id}")
    assert resp.status_code == 404


def test_product_detail_price_table_shows_only_current_high_low_change():
    client, Session_ = _make_client()
    t1 = datetime.datetime(2026, 1, 1)
    t2 = datetime.datetime(2026, 2, 1)
    with Session_() as session:
        cat = Category(name="顯示卡VGA")
        sub = Subcategory(name="NVIDIA", category=cat)
        session.add_all([cat, sub])
        session.flush()
        p = Product(category_id=cat.id, subcategory_id=sub.id, current_name="價格表格簡化測試",
                   current_price=18990, is_active=True, last_seen_at=t2, created_at=t1)
        session.add(p)
        session.flush()
        session.add(ProductName(product_id=p.id, name=p.current_name, first_seen_at=t1, last_seen_at=t2))
        snap = ScrapeSnapshot(fetched_at=t1, scrape_type="scheduled", status="success", created_at=t1)
        session.add(snap)
        session.flush()
        session.add(PriceHistory(product_id=p.id, price=20000, scraped_at=t1, snapshot_id=snap.id))
        session.add(PriceHistory(product_id=p.id, price=18990, scraped_at=t2, snapshot_id=snap.id))
        session.commit()
        product_id = p.id

    resp = client.get(f"/products/{product_id}")
    assert resp.status_code == 200
    assert "上次價格" not in resp.text
    assert "7 天最低" not in resp.text
    assert "30 天最低" not in resp.text
    assert "90 天最低" not in resp.text
    assert "歷史最低" in resp.text
    assert "歷史最高" in resp.text
    assert "較前次抓取" in resp.text


def test_product_detail_chart_has_no_apply_button_and_uses_change_listener():
    client, Session_ = _make_client()
    t = datetime.datetime(2026, 2, 1)
    with Session_() as session:
        cat = Category(name="顯示卡VGA")
        sub = Subcategory(name="NVIDIA", category=cat)
        session.add_all([cat, sub])
        session.flush()
        p = Product(category_id=cat.id, subcategory_id=sub.id, current_name="走勢圖自動更新測試",
                   current_price=100, is_active=True, last_seen_at=t, created_at=t)
        session.add(p)
        session.flush()
        session.add(ProductName(product_id=p.id, name=p.current_name, first_seen_at=t, last_seen_at=t))
        session.commit()
        product_id = p.id

    resp = client.get(f"/products/{product_id}")
    assert resp.status_code == 200
    assert 'id="rangeCustom"' not in resp.text
    assert ">套用<" not in resp.text
    assert "rangeStart" in resp.text and "'change'" in resp.text


def test_product_detail_compare_checkbox_replaces_same_category_dropdown():
    client, Session_ = _make_client()
    t = datetime.datetime(2026, 2, 1)
    with Session_() as session:
        cat = Category(name="顯示卡VGA")
        sub = Subcategory(name="NVIDIA", category=cat)
        session.add_all([cat, sub])
        session.flush()
        p = Product(category_id=cat.id, subcategory_id=sub.id, current_name="比較勾選測試",
                   current_price=100, is_active=True, last_seen_at=t, created_at=t)
        session.add(p)
        session.flush()
        session.add(ProductName(product_id=p.id, name=p.current_name, first_seen_at=t, last_seen_at=t))
        session.commit()
        product_id = p.id

    resp = client.get(f"/products/{product_id}")
    assert resp.status_code == 200
    assert 'id="compareToggle"' in resp.text
    assert "加入比較" in resp.text
    assert 'id="compareAdd"' not in resp.text
    assert "addCompare(" not in resp.text


def test_base_html_exposes_shared_compare_cart_helper():
    client, _Session_ = _make_client()
    resp = client.get("/")
    assert resp.status_code == 200
    assert "coolpcCompare" in resp.text
    assert 'id="compareNavLink"' in resp.text
