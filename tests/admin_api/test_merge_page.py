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
    # 商品名稱欄要佔表格一半以上寬度，不能被壓縮
    assert "width:55%" in resp.text
    # 欄寬仍要能手動拖曳調整
    assert "col-resizer" in resp.text
    assert "mousedown" in resp.text


def test_product_search_page_uses_and_semantics_for_space_separated_query():
    client, Session_ = _make_client()
    t = datetime.datetime(2026, 2, 1)
    with Session_() as session:
        cat = Category(name="顯示卡VGA")
        sub = Subcategory(name="NVIDIA", category=cat)
        session.add_all([cat, sub])
        session.flush()
        p1 = Product(category_id=cat.id, subcategory_id=sub.id, current_name="ASUS RTX 5070 PRIME 12G",
                     current_price=18990, is_active=True, first_seen_at=t, last_seen_at=t, created_at=t)
        p2 = Product(category_id=cat.id, subcategory_id=sub.id, current_name="MSI RTX 5080 GAMING 16G",
                     current_price=28990, is_active=True, first_seen_at=t, last_seen_at=t, created_at=t)
        session.add_all([p1, p2])
        session.flush()
        session.add_all([
            ProductName(product_id=p1.id, name=p1.current_name, first_seen_at=t, last_seen_at=t),
            ProductName(product_id=p2.id, name=p2.current_name, first_seen_at=t, last_seen_at=t),
        ])
        session.commit()

    # "RTX 5090" 兩個字都要同時命中才算符合；沒有任何商品同時含 "RTX" 和
    # "5090"，AND 語意應該完全查不到（OR 語意則會因為 "RTX" 命中兩張顯卡）。
    resp = client.get("/products", params={"q": "RTX 5090"})
    assert resp.status_code == 200
    assert "ASUS RTX 5070 PRIME 12G" not in resp.text
    assert "MSI RTX 5080 GAMING 16G" not in resp.text

    resp2 = client.get("/products", params={"q": "RTX 5070"})
    assert resp2.status_code == 200
    assert "ASUS RTX 5070 PRIME 12G" in resp2.text
    assert "MSI RTX 5080 GAMING 16G" not in resp2.text


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


def test_product_search_json_returns_matches_by_name():
    client, Session_ = _make_client()
    t = datetime.datetime(2026, 2, 1)
    with Session_() as session:
        cat = Category(name="顯示卡VGA")
        sub = Subcategory(name="NVIDIA", category=cat)
        session.add_all([cat, sub])
        session.flush()
        p = Product(category_id=cat.id, subcategory_id=sub.id, current_name="ASUS RTX 5070 搜尋測試",
                   current_price=18990, is_active=True, first_seen_at=t, last_seen_at=t, created_at=t)
        session.add(p)
        session.flush()
        session.add(ProductName(product_id=p.id, name=p.current_name, first_seen_at=t, last_seen_at=t))
        session.commit()
        p_id = p.id

    resp = client.get("/products/search-json", params={"q": "搜尋測試"})
    assert resp.status_code == 200
    data = resp.json()
    assert len(data) == 1
    assert data[0]["id"] == p_id
    assert data[0]["name"] == "ASUS RTX 5070 搜尋測試"
    assert data[0]["price"] == 18990
    assert data[0]["is_active"] is True


def test_product_search_json_empty_query_returns_empty_list():
    client, _Session_ = _make_client()
    resp = client.get("/products/search-json", params={"q": ""})
    assert resp.status_code == 200
    assert resp.json() == []


def test_product_search_json_and_match_finds_exact_product_among_many_newer():
    """搜尋一個商品的完整名稱時，即使有超過 10 個 last_seen_at 較新的其他商品，
    AND 比對也應該精確命中該商品本身（而不是被純 OR + LIMIT 10 擠出結果）。"""
    client, Session_ = _make_client()
    t = datetime.datetime(2026, 2, 1)
    with Session_() as session:
        cat = Category(name="顯示卡VGA")
        sub = Subcategory(name="NVIDIA", category=cat)
        session.add_all([cat, sub])
        session.flush()
        target = Product(category_id=cat.id, subcategory_id=sub.id,
                          current_name="ASUS RTX 5070 PRIME OC 12GB 特仕版",
                          current_price=19990, is_active=True,
                          first_seen_at=t, last_seen_at=t, created_at=t)
        session.add(target)
        session.flush()
        session.add(ProductName(product_id=target.id, name=target.current_name,
                                 first_seen_at=t, last_seen_at=t))
        newer = t + datetime.timedelta(days=1)
        for i in range(12):
            other = Product(category_id=cat.id, subcategory_id=sub.id,
                             current_name=f"其他商品 RTX {i}",
                             current_price=1000 + i, is_active=True,
                             first_seen_at=newer, last_seen_at=newer, created_at=newer)
            session.add(other)
            session.flush()
            session.add(ProductName(product_id=other.id, name=other.current_name,
                                     first_seen_at=newer, last_seen_at=newer))
        session.commit()
        target_id = target.id

    resp = client.get("/products/search-json", params={"q": "ASUS RTX 5070 PRIME OC 12GB 特仕版"})
    assert resp.status_code == 200
    ids = [row["id"] for row in resp.json()]
    assert target_id in ids


def test_product_search_json_never_falls_back_to_or():
    """AND 比對查無結果時，必須直接回傳空陣列，不能退回 OR 語意撈出一堆不
    精確的候選商品——寧可查無結果，也不要讓不精確的商品混進來。"""
    client, Session_ = _make_client()
    t = datetime.datetime(2026, 2, 1)
    with Session_() as session:
        cat = Category(name="顯示卡VGA")
        sub = Subcategory(name="NVIDIA", category=cat)
        session.add_all([cat, sub])
        session.flush()
        a = Product(category_id=cat.id, subcategory_id=sub.id, current_name="ASUS RTX 5070 PRIME 12G",
                    current_price=18990, is_active=True, first_seen_at=t, last_seen_at=t, created_at=t)
        b = Product(category_id=cat.id, subcategory_id=sub.id, current_name="MSI RTX 5080 GAMING 16G",
                    current_price=28990, is_active=True, first_seen_at=t, last_seen_at=t, created_at=t)
        session.add_all([a, b])
        session.flush()
        session.add_all([
            ProductName(product_id=a.id, name=a.current_name, first_seen_at=t, last_seen_at=t),
            ProductName(product_id=b.id, name=b.current_name, first_seen_at=t, last_seen_at=t),
        ])
        session.commit()

    resp = client.get("/products/search-json", params={"q": "RTX 5090"})
    assert resp.status_code == 200
    assert resp.json() == []


def test_product_search_json_finds_non_contiguous_tokens_but_excludes_wrong_model():
    """使用者提供的具體案例：搜尋 "ZOTAC 3050" 要找到 "ZOTAC RTX3050 ECO
    SOLO"（3050 沒有以獨立單字出現，是夾在 RTX3050 裡面），但不能找到
    "ZOTAC GT730 2GB Zone Edition"（完全沒有 3050）。"""
    client, Session_ = _make_client()
    t = datetime.datetime(2026, 2, 1)
    with Session_() as session:
        cat = Category(name="顯示卡VGA")
        sub = Subcategory(name="NVIDIA", category=cat)
        session.add_all([cat, sub])
        session.flush()
        a = Product(category_id=cat.id, subcategory_id=sub.id, current_name="ZOTAC RTX3050 ECO SOLO",
                    current_price=6490, is_active=True, first_seen_at=t, last_seen_at=t, created_at=t)
        b = Product(category_id=cat.id, subcategory_id=sub.id, current_name="ZOTAC GT730 2GB Zone Edition",
                    current_price=2490, is_active=True, first_seen_at=t, last_seen_at=t, created_at=t)
        session.add_all([a, b])
        session.flush()
        session.add_all([
            ProductName(product_id=a.id, name=a.current_name, first_seen_at=t, last_seen_at=t),
            ProductName(product_id=b.id, name=b.current_name, first_seen_at=t, last_seen_at=t),
        ])
        session.commit()

    resp = client.get("/products/search-json", params={"q": "ZOTAC 3050"})
    assert resp.status_code == 200
    names = [row["name"] for row in resp.json()]
    assert names == ["ZOTAC RTX3050 ECO SOLO"]


def test_merge_page_shows_more_than_50_merge_logs():
    """批量合併一次最多可產生 100 組 MergeLog，/merge 頁面的上限必須容得下，
    否則超過 50 筆之後的紀錄就永遠無法從管理介面被 Undo。"""
    client, Session_ = _make_client()
    source_id, target_id = _seed_two_products(Session_)
    t = datetime.datetime(2026, 2, 1)
    with Session_() as session:
        for i in range(60):
            session.add(MergeLog(source_product_id=source_id, target_product_id=target_id,
                                  merged_at=t + datetime.timedelta(minutes=i)))
        session.commit()

    resp = client.get("/merge")
    assert resp.status_code == 200
    assert resp.text.count("已合併") >= 60


def test_merge_page_has_single_combined_id_or_name_inputs():
    client, _Session_ = _make_client()
    resp = client.get("/merge")
    assert resp.status_code == 200
    assert 'id="sourceInput"' in resp.text
    assert 'id="targetInput"' in resp.text
    assert 'name="source_id"' in resp.text
    assert 'name="target_id"' in resp.text
    # 舊版分離的搜尋框 + 備用 ID 框已合併成單一輸入框
    assert 'id="sourceSearch"' not in resp.text
    assert 'id="sourceId"' not in resp.text
    assert "備用" not in resp.text
    assert resp.text.count('name="source_id"') == 1
    assert resp.text.count('name="target_id"') == 1
