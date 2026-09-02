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


def test_search_page_renders_seeded_product():
    client, Session_ = _make_client()
    t = datetime.datetime(2026, 2, 1)
    with Session_() as session:
        cat = Category(name="顯示卡VGA")
        sub = Subcategory(name="NVIDIA", category=cat)
        session.add_all([cat, sub])
        session.flush()
        p = Product(category_id=cat.id, subcategory_id=sub.id, current_name="ASUS RTX 5070 PRIME 12G",
                    current_price=18990, is_active=True, first_seen_at=t, last_seen_at=t, created_at=t)
        session.add(p)
        session.flush()
        session.add(ProductName(product_id=p.id, name=p.current_name, first_seen_at=t, last_seen_at=t))
        session.add(PriceHistory(product_id=p.id, price=18990, status=None, badges="",
                                  scraped_at=t, snapshot_id=1))
        session.commit()

    resp = client.get("/")
    assert resp.status_code == 200
    assert "ASUS RTX 5070 PRIME 12G" in resp.text
    assert "顯示卡VGA" in resp.text
    assert "18,990" in resp.text


def test_search_page_pagination_link_preserves_query():
    client, Session_ = _make_client()
    t = datetime.datetime(2026, 2, 1)
    with Session_() as session:
        cat = Category(name="顯示卡VGA")
        sub = Subcategory(name="NVIDIA", category=cat)
        session.add_all([cat, sub])
        session.flush()
        for i in range(35):
            name = f"ASUS 商品{i}"
            p = Product(category_id=cat.id, subcategory_id=sub.id, current_name=name,
                        current_price=1000 + i, is_active=True, first_seen_at=t, last_seen_at=t, created_at=t)
            session.add(p)
            session.flush()
            session.add(ProductName(product_id=p.id, name=name, first_seen_at=t, last_seen_at=t))
        session.commit()

    resp = client.get("/", params={"sort": "price_desc", "page": 1})
    assert resp.status_code == 200
    assert "sort=price_desc" in resp.text
    assert "page=2" in resp.text
