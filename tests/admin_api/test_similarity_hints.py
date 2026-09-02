import datetime
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool
from coolpc.db.models import Base, Category, Subcategory, Product, SimilarityHint
from coolpc.admin_api.app import app
from coolpc.admin_api.dependencies import get_session


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


def test_similarity_hints_page_lists_candidates():
    client, Session_ = _make_client()
    t = datetime.datetime(2026, 2, 1)
    with Session_() as session:
        cat = Category(name="顯示卡VGA")
        sub = Subcategory(name="NVIDIA", category=cat)
        session.add_all([cat, sub])
        session.flush()
        a = Product(category_id=cat.id, subcategory_id=sub.id, current_name="ASUS RTX 5070 PRIME 12G",
                   current_price=100, is_active=False, first_seen_at=t, last_seen_at=t, created_at=t)
        b = Product(category_id=cat.id, subcategory_id=sub.id, current_name="ASUS RTX 5070 PRIME OC 12GB",
                   current_price=200, is_active=True, first_seen_at=t, last_seen_at=t, created_at=t)
        session.add_all([a, b])
        session.flush()
        session.add(SimilarityHint(product_a_id=a.id, product_b_id=b.id, score=0.85,
                                    computed_at=t, dismissed=False))
        session.commit()

    resp = client.get("/similarity-hints")
    assert resp.status_code == 200
    assert "ASUS RTX 5070 PRIME 12G" in resp.text
    assert "85%" in resp.text


def test_similarity_hints_refresh_creates_new_hints():
    client, Session_ = _make_client()
    t = datetime.datetime(2026, 2, 1)
    with Session_() as session:
        cat = Category(name="顯示卡VGA")
        sub = Subcategory(name="NVIDIA", category=cat)
        session.add_all([cat, sub])
        session.flush()
        a = Product(category_id=cat.id, subcategory_id=sub.id, current_name="ASUS RTX 5070 PRIME 12G",
                   current_price=100, is_active=False, first_seen_at=t, last_seen_at=t, created_at=t)
        b = Product(category_id=cat.id, subcategory_id=sub.id, current_name="ASUS RTX 5070 PRIME OC 12GB",
                   current_price=200, is_active=True, first_seen_at=t, last_seen_at=t, created_at=t)
        session.add_all([a, b])
        session.commit()

    resp = client.post("/similarity-hints/refresh", follow_redirects=False)
    assert resp.status_code == 303
    resp2 = client.get("/similarity-hints")
    assert "ASUS RTX 5070 PRIME 12G" in resp2.text


def test_dismiss_hint_removes_it_from_list():
    client, Session_ = _make_client()
    t = datetime.datetime(2026, 2, 1)
    with Session_() as session:
        cat = Category(name="顯示卡VGA")
        sub = Subcategory(name="NVIDIA", category=cat)
        session.add_all([cat, sub])
        session.flush()
        a = Product(category_id=cat.id, subcategory_id=sub.id, current_name="商品A獨特字串",
                   current_price=100, is_active=True, first_seen_at=t, last_seen_at=t, created_at=t)
        b = Product(category_id=cat.id, subcategory_id=sub.id, current_name="商品B獨特字串",
                   current_price=200, is_active=True, first_seen_at=t, last_seen_at=t, created_at=t)
        session.add_all([a, b])
        session.flush()
        hint = SimilarityHint(product_a_id=a.id, product_b_id=b.id, score=0.8, computed_at=t, dismissed=False)
        session.add(hint)
        session.commit()
        hint_id = hint.id

    before = client.get("/similarity-hints")
    assert "商品A獨特字串" in before.text

    resp = client.post(f"/similarity-hints/{hint_id}/dismiss", follow_redirects=False)
    assert resp.status_code == 303
    after = client.get("/similarity-hints")
    assert "商品A獨特字串" not in after.text
