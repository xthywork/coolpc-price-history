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
        "sqlite:///:memory:", connect_args={"check_same_thread": False}, poolclass=StaticPool
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


def _seed(Session_, name, price, t):
    with Session_() as session:
        cat = session.query(Category).filter_by(name="顯示卡VGA").one_or_none() or Category(name="顯示卡VGA")
        session.add(cat)
        session.flush()
        sub = session.query(Subcategory).filter_by(category_id=cat.id, name="NVIDIA").one_or_none()
        if sub is None:
            sub = Subcategory(name="NVIDIA", category=cat)
            session.add(sub)
            session.flush()
        p = Product(category_id=cat.id, subcategory_id=sub.id, current_name=name,
                    current_price=price, is_active=True, last_seen_at=t, created_at=t)
        session.add(p)
        session.flush()
        session.add(ProductName(product_id=p.id, name=name, first_seen_at=t, last_seen_at=t))
        session.add(PriceHistory(product_id=p.id, price=price, status=None, badges="",
                                  scraped_at=t, snapshot_id=1))
        session.commit()
        return p.id


def test_compare_rejects_too_few_ids():
    client, Session_ = _make_client()
    pid = _seed(Session_, "A", 100, datetime.datetime(2026, 2, 1))
    resp = client.get("/api/compare", params={"ids": str(pid)})
    assert resp.status_code == 400


def test_compare_rejects_too_many_ids():
    client, Session_ = _make_client()
    t = datetime.datetime(2026, 2, 1)
    ids = [_seed(Session_, f"P{i}", 100 + i, t) for i in range(21)]
    resp = client.get("/api/compare", params={"ids": ",".join(str(i) for i in ids)})
    assert resp.status_code == 400


def test_compare_rejects_duplicate_ids():
    client, Session_ = _make_client()
    pid = _seed(Session_, "重複比較商品", 100, datetime.datetime(2026, 2, 1))

    resp = client.get("/api/compare", params={"ids": f"{pid},{pid}"})

    assert resp.status_code == 400


def test_compare_accepts_twenty_ids():
    client, Session_ = _make_client()
    t = datetime.datetime(2026, 2, 1)
    ids = [_seed(Session_, f"P{i}", 100 + i, t) for i in range(20)]

    resp = client.get("/api/compare", params={"ids": ",".join(str(i) for i in ids)})

    assert resp.status_code == 200
    assert {item["id"] for item in resp.json()["items"]} == set(ids)


def test_compare_returns_items_and_series():
    client, Session_ = _make_client()
    t = datetime.datetime(2026, 2, 1)
    id1 = _seed(Session_, "ASUS RTX 5070 PRIME 12G", 18990, t)
    id2 = _seed(Session_, "微星 RTX3050 VENTUS 2X E 6G OC", 7990, t)

    resp = client.get("/api/compare", params={"ids": f"{id1},{id2}"})
    assert resp.status_code == 200
    data = resp.json()
    assert len(data["items"]) == 2
    assert {i["id"] for i in data["items"]} == {id1, id2}
    assert len(data["series"]) == 2


def test_compare_404_when_product_missing():
    client, Session_ = _make_client()
    pid = _seed(Session_, "A", 100, datetime.datetime(2026, 2, 1))
    resp = client.get("/api/compare", params={"ids": f"{pid},99999"})
    assert resp.status_code == 404


def test_compare_404_for_merged_away_source_id():
    # Regression test: including a merged-away SOURCE product's own id in the
    # comparison list must 404 the whole request, not silently include that
    # source's stale pre-merge data (get_merged_group_product_ids is directional
    # and only resolves correctly from the merge TARGET's id).
    client, Session_ = _make_client()
    t0 = datetime.datetime(2026, 2, 1)
    t1 = datetime.datetime(2026, 2, 2)
    other_id = _seed(Session_, "Other", 300, t0)
    with Session_() as session:
        cat = session.query(Category).filter_by(name="顯示卡VGA").one()
        sub = session.query(Subcategory).filter_by(category_id=cat.id, name="NVIDIA").one()
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

    resp = client.get("/api/compare", params={"ids": f"{source_id},{other_id}"})
    assert resp.status_code == 404
