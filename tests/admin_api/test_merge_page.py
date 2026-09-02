import datetime
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool
from coolpc.db.models import Base, Category, Subcategory, Product, ProductName, MergeLog
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


def _seed_two_products(Session_):
    t = datetime.datetime(2026, 2, 1)
    with Session_() as session:
        cat = Category(name="顯示卡VGA")
        sub = Subcategory(name="NVIDIA", category=cat)
        session.add_all([cat, sub])
        session.flush()
        source = Product(category_id=cat.id, subcategory_id=sub.id, current_name="ASUS RTX 5070 PRIME 12G",
                         current_price=18990, is_active=False, first_seen_at=t, last_seen_at=t, created_at=t)
        target = Product(category_id=cat.id, subcategory_id=sub.id, current_name="ASUS RTX 5070 PRIME OC 12GB",
                         current_price=19990, is_active=True, first_seen_at=t, last_seen_at=t, created_at=t)
        session.add_all([source, target])
        session.flush()
        session.add_all([
            ProductName(product_id=source.id, name=source.current_name, first_seen_at=t, last_seen_at=t),
            ProductName(product_id=target.id, name=target.current_name, first_seen_at=t, last_seen_at=t),
        ])
        session.commit()
        return source.id, target.id


def test_product_search_page_shows_id_and_name():
    client, Session_ = _make_client()
    source_id, _ = _seed_two_products(Session_)
    resp = client.get("/products")
    assert resp.status_code == 200
    assert str(source_id) in resp.text
    assert "ASUS RTX 5070 PRIME 12G" in resp.text


def test_merge_form_success_then_undo_flow():
    client, Session_ = _make_client()
    source_id, target_id = _seed_two_products(Session_)

    resp = client.post("/merge", data={"source_id": source_id, "target_id": target_id},
                        follow_redirects=False)
    assert resp.status_code == 303
    assert "message" in resp.headers["location"]

    merge_page = client.get("/merge")
    assert "已合併" in merge_page.text
    assert "ASUS RTX 5070 PRIME 12G" in merge_page.text

    with Session_() as session:
        log = session.query(MergeLog).one()
        log_id = log.id

    undo_resp = client.post(f"/merge/{log_id}/undo", follow_redirects=False)
    assert undo_resp.status_code == 303

    merge_page_after = client.get("/merge")
    assert "已復原" in merge_page_after.text


def test_merge_same_source_and_target_shows_error():
    client, Session_ = _make_client()
    source_id, _ = _seed_two_products(Session_)
    resp = client.post("/merge", data={"source_id": source_id, "target_id": source_id},
                        follow_redirects=False)
    assert resp.status_code == 303
    assert "error" in resp.headers["location"]


def test_undo_already_undone_merge_shows_error_via_http():
    """MergeError from an already-undone merge must surface through the HTTP layer,
    not crash and not silently look like a success."""
    client, Session_ = _make_client()
    source_id, target_id = _seed_two_products(Session_)

    client.post("/merge", data={"source_id": source_id, "target_id": target_id},
                follow_redirects=False)
    with Session_() as session:
        log_id = session.query(MergeLog).one().id

    first_undo = client.post(f"/merge/{log_id}/undo", follow_redirects=False)
    assert first_undo.status_code == 303
    assert "message" in first_undo.headers["location"]

    second_undo = client.post(f"/merge/{log_id}/undo", follow_redirects=False)
    assert second_undo.status_code == 303
    assert "error" in second_undo.headers["location"]

    merge_page = client.get("/merge")
    assert resp_contains_undone_once(merge_page.text)


def resp_contains_undone_once(text: str) -> bool:
    return "已復原" in text
