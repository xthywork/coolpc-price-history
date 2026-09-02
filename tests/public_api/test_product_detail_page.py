import datetime
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, text
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool
from coolpc.db.models import Base, Category, Subcategory, Product, ProductName, PriceHistory
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
                    current_price=19990, is_active=True, first_seen_at=t0, last_seen_at=t1, created_at=t0)
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
    assert "chart.js" in resp.text.lower()
    assert "18,990" in resp.text  # 歷史價格列表出現舊價格


def test_product_detail_page_404_for_missing():
    client, _ = _make_client()
    resp = client.get("/products/999")
    assert resp.status_code == 404


def test_product_detail_page_shows_same_category_quick_compare():
    client, Session_ = _make_client()
    t = datetime.datetime(2026, 2, 1)
    with Session_() as session:
        cat = Category(name="顯示卡VGA")
        sub = Subcategory(name="NVIDIA", category=cat)
        session.add_all([cat, sub])
        session.flush()
        p1 = Product(category_id=cat.id, subcategory_id=sub.id, current_name="A卡",
                     current_price=1000, is_active=True, first_seen_at=t, last_seen_at=t, created_at=t)
        p2 = Product(category_id=cat.id, subcategory_id=sub.id, current_name="B卡",
                     current_price=2000, is_active=True, first_seen_at=t, last_seen_at=t, created_at=t)
        session.add_all([p1, p2])
        session.commit()
        pid = p1.id

    resp = client.get(f"/products/{pid}")
    assert "B卡" in resp.text


def test_product_detail_page_404_for_merged_away_product():
    client, Session_ = _make_client()
    t = datetime.datetime(2026, 2, 1)
    with Session_() as session:
        cat = Category(name="顯示卡VGA")
        sub = Subcategory(name="NVIDIA", category=cat)
        session.add_all([cat, sub])
        session.flush()
        target = Product(category_id=cat.id, subcategory_id=sub.id, current_name="目標商品",
                          current_price=1000, is_active=True, first_seen_at=t, last_seen_at=t, created_at=t)
        session.add(target)
        session.flush()
        source = Product(category_id=cat.id, subcategory_id=sub.id, current_name="來源商品",
                          current_price=1000, is_active=False, first_seen_at=t, last_seen_at=t,
                          created_at=t, merged_into_id=target.id)
        session.add(source)
        session.commit()
        source_id = source.id

    resp = client.get(f"/products/{source_id}")
    assert resp.status_code == 404
