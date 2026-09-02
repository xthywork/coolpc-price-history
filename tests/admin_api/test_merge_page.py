import datetime
from urllib.parse import urlparse, parse_qs
from markupsafe import escape
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool
from coolpc.db.models import Base, Category, Subcategory, Product, ProductName, MergeLog
from coolpc.admin_api.app import app
from coolpc.admin_api.dependencies import get_session
from coolpc.admin_api.routers import products as products_router
from coolpc.merging.service import MergeError


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


def test_merge_error_message_with_special_characters_survives_redirect(monkeypatch):
    """Regression test for the redirect-URL-building fix: error/message text must be
    properly urlencoded, not f-string-interpolated raw into the query string. Real
    MergeError messages from Task 15 never happen to contain '&', '=', or '#' today, so
    this monkeypatches merge_products (as imported into the products router module) to
    raise a MergeError whose message deliberately contains those query-string-special
    characters, and verifies the text survives the redirect round-trip unmangled -
    proving the query string isn't fragmented or truncated."""
    client, Session_ = _make_client()
    source_id, target_id = _seed_two_products(Session_)

    tricky_message = "錯誤：a&b=c#d"

    def fake_merge_products(session, source_id, target_id):
        raise MergeError(tricky_message)

    monkeypatch.setattr(products_router, "merge_products", fake_merge_products)

    resp = client.post("/merge", data={"source_id": source_id, "target_id": target_id},
                        follow_redirects=False)
    assert resp.status_code == 303
    location = resp.headers["location"]

    # The query string must contain exactly one 'error' param with the full, unmangled
    # message - not fragmented into spurious extra params by the raw '&'/'=' characters.
    parsed_qs = parse_qs(urlparse(location).query)
    assert parsed_qs["error"] == [tricky_message]

    merge_page = client.get(location)
    assert merge_page.status_code == 200
    # The template HTML-escapes {{ error }} on render (Jinja2 autoescape turns '&' into
    # '&amp;'), so compare against the escaped form here - the query-string-level
    # round-trip integrity was already proven above via parse_qs on the raw redirect URL.
    assert str(escape(tricky_message)) in merge_page.text
