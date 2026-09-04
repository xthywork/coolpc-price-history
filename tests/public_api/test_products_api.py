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


def test_list_categories_returns_seeded_categories():
    client, Session_ = _make_client()
    with Session_() as session:
        session.add(Category(name="顯示卡VGA"))
        session.commit()

    resp = client.get("/api/categories")
    assert resp.status_code == 200
    assert any(c["name"] == "顯示卡VGA" for c in resp.json())


def test_list_categories_prefers_display_name_when_set():
    client, Session_ = _make_client()
    with Session_() as session:
        session.add(Category(name="顯示卡VGA", display_name="顯卡"))
        session.commit()

    resp = client.get("/api/categories")
    assert resp.status_code == 200
    names = [c["name"] for c in resp.json()]
    assert "顯卡" in names
    assert "顯示卡VGA" not in names


def _seed_product(Session_, name, price, category_name="顯示卡VGA", subcategory_name="NVIDIA"):
    t = datetime.datetime(2026, 2, 1)
    with Session_() as session:
        cat = session.query(Category).filter_by(name=category_name).one_or_none() or Category(name=category_name)
        session.add(cat)
        session.flush()
        sub = (
            session.query(Subcategory)
            .filter_by(category_id=cat.id, name=subcategory_name)
            .one_or_none()
            or Subcategory(name=subcategory_name, category=cat)
        )
        session.add(sub)
        session.flush()
        p = Product(category_id=cat.id, subcategory_id=sub.id, current_name=name,
                    current_price=price, is_active=True, first_seen_at=t, last_seen_at=t, created_at=t)
        session.add(p)
        session.flush()
        session.add(ProductName(product_id=p.id, name=name, first_seen_at=t, last_seen_at=t))
        session.add(PriceHistory(product_id=p.id, price=price, status=None, badges="",
                                  scraped_at=t, snapshot_id=1))
        session.commit()
        return p.id


def test_list_products_returns_items_with_stats():
    client, Session_ = _make_client()
    _seed_product(Session_, "ASUS RTX 5070 PRIME 12G", 18990)

    resp = client.get("/api/products")
    assert resp.status_code == 200
    data = resp.json()
    assert data["total"] == 1
    assert data["items"][0]["current_name"] == "ASUS RTX 5070 PRIME 12G"
    assert data["items"][0]["current_price"] == 18990
    assert data["items"][0]["is_active"] is True


def test_list_products_filters_by_fts_query():
    client, Session_ = _make_client()
    _seed_product(Session_, "Synology HAT3300 4TB【限搭NAS主機】", 6890,
                   category_name="固態硬碟", subcategory_name="NAS碟")
    _seed_product(Session_, "ASUS RTX 5070 PRIME 12G", 18990)

    resp = client.get("/api/products", params={"q": "限搭"})
    data = resp.json()
    assert data["total"] == 1
    assert data["items"][0]["current_name"].startswith("Synology")


def test_list_products_filters_by_category_and_price():
    client, Session_ = _make_client()
    vga_id = _seed_product(Session_, "ASUS RTX 5070 PRIME 12G", 18990)
    _seed_product(Session_, "微星 RTX3050 VENTUS 2X E 6G OC", 7990)

    with Session_() as session:
        vga_cat_id = session.get(Product, vga_id).category_id

    resp = client.get("/api/products", params={"category_id": vga_cat_id, "min_price": 10000})
    data = resp.json()
    assert data["total"] == 1
    assert data["items"][0]["current_name"].startswith("ASUS")


def test_list_products_accepts_blank_optional_query_params_without_422():
    # 前端表單或客戶端組裝查詢字串時常會送出空字串（而非完全省略參數），
    # 例如 category_id=&min_price=&is_active=；這些欄位是 int/bool/float，
    # 必須把空字串視為「未指定」而不是回 422。
    client, _Session_ = _make_client()
    resp = client.get("/api/products", params={
        "q": "", "category_id": "", "subcategory_id": "", "brand": "", "model": "",
        "min_price": "", "max_price": "", "is_active": "",
    })
    assert resp.status_code == 200
    assert resp.json()["total"] == 0


def test_autocomplete_uses_and_semantics_not_or():
    client, Session_ = _make_client()
    _seed_product(Session_, "ASUS RTX 5070 PRIME 12G", 18990)
    _seed_product(Session_, "MSI RTX 5080 GAMING 16G", 28990)

    # 明確要求 OR 語意的 /api/products：兩個商品都含 "RTX"，OR 語意下
    # "RTX 5070" 兩張顯卡都會命中（"RTX" 這個 token 兩者都有）。
    or_resp = client.get("/api/products", params={"q": "RTX 5070", "q_match": "or"})
    assert or_resp.json()["total"] == 2

    # 同樣的查詢字串，AND 語意的自動完成端點必須只精準命中真正同時包含
    # "RTX" 和 "5070" 的那一個商品，不能像 OR 一樣把 MSI 那張也算進去
    # （這正是自動完成要換成 AND 語意的原因：OR 在真實資料上太寬鬆，會把
    # 真正要找的商品淹沒在大量無關結果裡）。
    and_resp = client.get("/api/products/autocomplete", params={"q": "RTX 5070"})
    assert and_resp.status_code == 200
    assert and_resp.json()["total"] == 1
    assert and_resp.json()["items"][0]["current_name"] == "ASUS RTX 5070 PRIME 12G"


def test_autocomplete_never_falls_back_to_or():
    client, Session_ = _make_client()
    _seed_product(Session_, "Synology HAT3300 4TB NAS專用碟", 6890)

    # AND 完全查無結果時（例如查詢分段各自命中不同商品或根本查無此字），
    # 必須直接回傳空結果，不能退回 OR 語意撈出不精確的候選商品。
    resp = client.get("/api/products/autocomplete", params={"q": "4TB 不存在的字串"})
    assert resp.status_code == 200
    assert resp.json()["total"] == 0
    assert resp.json()["items"] == []


def test_autocomplete_empty_query_returns_empty_list():
    client, _Session_ = _make_client()
    resp = client.get("/api/products/autocomplete", params={"q": ""})
    assert resp.status_code == 200
    assert resp.json()["items"] == []
    assert resp.json()["total"] == 0


def test_autocomplete_does_not_cap_results_at_ten():
    """搜尋結果不能被人為限制在 10 筆，超過 10 個都符合 AND 條件的商品要
    全部列出來。"""
    client, Session_ = _make_client()
    for i in range(15):
        _seed_product(Session_, f"ZOTAC RTX3050 型號{i}", 6000 + i)

    resp = client.get("/api/products/autocomplete", params={"q": "ZOTAC 3050"})
    assert resp.status_code == 200
    assert resp.json()["total"] == 15
    assert len(resp.json()["items"]) == 15
