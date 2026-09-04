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


def test_get_product_detail_includes_historical_names_and_stats():
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

    resp = client.get(f"/api/products/{pid}")
    assert resp.status_code == 200
    data = resp.json()
    assert data["current_name"] == "ASUS RTX 5070 v2"
    assert set(data["historical_names"]) == {"ASUS RTX 5070", "ASUS RTX 5070 v2"}
    assert data["change_amount"] == 1000
    assert data["stats"]["all_time_low"] == 18990


def test_get_product_detail_404_for_missing():
    client, _ = _make_client()
    resp = client.get("/api/products/999")
    assert resp.status_code == 404


def test_get_product_prices_returns_ordered_series():
    client, Session_ = _make_client()
    t0 = datetime.datetime(2026, 2, 1)
    t1 = datetime.datetime(2026, 2, 2)
    with Session_() as session:
        cat = Category(name="C")
        sub = Subcategory(name="S", category=cat)
        session.add_all([cat, sub])
        session.flush()
        p = Product(category_id=cat.id, subcategory_id=sub.id, current_name="X",
                    current_price=200, is_active=True, last_seen_at=t1, created_at=t0)
        session.add(p)
        session.flush()
        session.add_all([
            PriceHistory(product_id=p.id, price=100, status=None, badges="", scraped_at=t0, snapshot_id=1),
            PriceHistory(product_id=p.id, price=200, status=None, badges="", scraped_at=t1, snapshot_id=2),
        ])
        session.commit()
        pid = p.id

    resp = client.get(f"/api/products/{pid}/prices")
    data = resp.json()
    assert len(data) == 2
    assert data[0]["price"] == 100
    assert data[1]["price"] == 200


def test_get_product_stats_endpoint():
    client, Session_ = _make_client()
    t0 = datetime.datetime(2026, 2, 1)
    with Session_() as session:
        cat = Category(name="C")
        sub = Subcategory(name="S", category=cat)
        session.add_all([cat, sub])
        session.flush()
        p = Product(category_id=cat.id, subcategory_id=sub.id, current_name="X",
                    current_price=500, is_active=True, last_seen_at=t0, created_at=t0)
        session.add(p)
        session.flush()
        session.add(PriceHistory(product_id=p.id, price=500, status=None, badges="",
                                  scraped_at=t0, snapshot_id=1))
        session.commit()
        pid = p.id

    resp = client.get(f"/api/products/{pid}/stats")
    assert resp.status_code == 200
    assert resp.json()["all_time_low"] == 500


def test_get_product_prices_404_for_merged_away_source():
    # Regression test: querying /prices with a merged-away SOURCE product's own id
    # must 404, not silently return that source's stale pre-merge history.
    # get_merged_group_product_ids is directional (finds products whose
    # merged_into_id == the given id), so passing the source's own id resolves to
    # just [source_id] alone, excluding the target's real/current data.
    client, Session_ = _make_client()
    t0 = datetime.datetime(2026, 2, 1)
    t1 = datetime.datetime(2026, 2, 2)
    with Session_() as session:
        cat = Category(name="C")
        sub = Subcategory(name="S", category=cat)
        session.add_all([cat, sub])
        session.flush()
        target = Product(category_id=cat.id, subcategory_id=sub.id, current_name="Target",
                          current_price=200, is_active=True, last_seen_at=t1,
                          created_at=t0)
        session.add(target)
        session.flush()
        source = Product(category_id=cat.id, subcategory_id=sub.id, current_name="Source (merged)",
                          current_price=999, is_active=False, last_seen_at=t0,
                          created_at=t0, merged_into_id=target.id)
        session.add(source)
        session.flush()
        session.add_all([
            PriceHistory(product_id=source.id, price=999, status=None, badges="",
                          scraped_at=t0, snapshot_id=1),
            PriceHistory(product_id=target.id, price=200, status=None, badges="",
                          scraped_at=t1, snapshot_id=2),
        ])
        session.commit()
        source_id = source.id

    resp = client.get(f"/api/products/{source_id}/prices")
    assert resp.status_code == 404


def test_get_product_stats_404_for_merged_away_source():
    client, Session_ = _make_client()
    t0 = datetime.datetime(2026, 2, 1)
    t1 = datetime.datetime(2026, 2, 2)
    with Session_() as session:
        cat = Category(name="C")
        sub = Subcategory(name="S", category=cat)
        session.add_all([cat, sub])
        session.flush()
        target = Product(category_id=cat.id, subcategory_id=sub.id, current_name="Target",
                          current_price=200, is_active=True, last_seen_at=t1,
                          created_at=t0)
        session.add(target)
        session.flush()
        source = Product(category_id=cat.id, subcategory_id=sub.id, current_name="Source (merged)",
                          current_price=999, is_active=False, last_seen_at=t0,
                          created_at=t0, merged_into_id=target.id)
        session.add(source)
        session.flush()
        session.add_all([
            PriceHistory(product_id=source.id, price=999, status=None, badges="",
                          scraped_at=t0, snapshot_id=1),
            PriceHistory(product_id=target.id, price=200, status=None, badges="",
                          scraped_at=t1, snapshot_id=2),
        ])
        session.commit()
        source_id = source.id

    resp = client.get(f"/api/products/{source_id}/stats")
    assert resp.status_code == 404
