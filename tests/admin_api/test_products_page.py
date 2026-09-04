import datetime
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool
from coolpc.db.models import Base, Category, Subcategory, Product
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


def _seed_product(Session_, **overrides):
    t = datetime.datetime(2026, 2, 1)
    with Session_() as session:
        cat = overrides.pop("category", None)
        if cat is None:
            cat = Category(name="顯示卡VGA")
            session.add(cat)
            session.flush()
        sub = overrides.pop("subcategory", None)
        if sub is None:
            sub = Subcategory(name="NVIDIA", category_id=cat.id)
            session.add(sub)
            session.flush()
        defaults = dict(
            category_id=cat.id, subcategory_id=sub.id, current_name="ASUS RTX 5070 PRIME 12G",
            brand="ASUS", model="RTX5070-12G", current_price=18990, is_active=True,
            last_seen_at=t, created_at=t,
        )
        defaults.update(overrides)
        product = Product(**defaults)
        session.add(product)
        session.commit()
        return product.id, cat.id, sub.id


def _seed_many_products(Session_, count):
    t = datetime.datetime(2026, 2, 1)
    with Session_() as session:
        cat = Category(name="顯示卡VGA")
        session.add(cat)
        session.flush()
        sub = Subcategory(name="NVIDIA", category_id=cat.id)
        session.add(sub)
        session.flush()
        for i in range(count):
            session.add(Product(
                category_id=cat.id, subcategory_id=sub.id, current_name=f"商品 {i:04d}",
                current_price=1000 + i, is_active=True, last_seen_at=t, created_at=t,
            ))
        session.commit()


def test_products_page_shows_required_columns():
    client, Session_ = _make_client()
    pid, _, _ = _seed_product(Session_)
    resp = client.get("/products")
    assert resp.status_code == 200
    for header in ["ID", "商品名稱", "品牌", "型號", "目前價格", "是否在售", "建立時間"]:
        assert f">{header}<" in resp.text
    assert "ASUS" in resp.text
    assert "RTX5070-12G" in resp.text
    assert "2026-02-01" in resp.text


def test_products_page_search_input_is_wide_with_button_beside():
    client, _Session_ = _make_client()
    resp = client.get("/products")
    assert resp.status_code == 200
    pos_q = resp.text.find('name="q"')
    pos_button = resp.text.find(">搜尋<")
    assert pos_q != -1 and pos_button != -1
    assert pos_q < pos_button
    assert "flex:1" in resp.text


def test_products_page_has_numbered_pagination_and_page_size_select():
    client, Session_ = _make_client()
    _seed_many_products(Session_, 25)
    resp = client.get("/products", params={"page_size": "10"})
    assert resp.status_code == 200
    assert 'class="pagination"' in resp.text
    assert 'id="pageSizeSelect"' in resp.text
    assert 'id="jumpPageInput"' in resp.text
    assert "每頁 10 筆" in resp.text
    assert "全部顯示" in resp.text
    resp2 = client.get("/products", params={"page_size": "10", "page": "2"})
    assert "商品 0010" in resp2.text
    assert "商品 0000" not in resp2.text


def test_products_page_preserves_scroll_position_on_page_size_change():
    client, _Session_ = _make_client()
    resp = client.get("/products")
    change_start = resp.text.find("pageSizeSelect.addEventListener('change'")
    change_end = resp.text.find("});", change_start)
    handler_body = resp.text[change_start:change_end]
    assert "sessionStorage.setItem('coolpc_admin_products_scroll'" in handler_body
    assert "window.scrollY" in handler_body
    restore_pos = resp.text.find("sessionStorage.getItem('coolpc_admin_products_scroll')")
    pagination_pos = resp.text.find('class="pagination"')
    assert restore_pos != -1 and pagination_pos != -1
    assert restore_pos > pagination_pos


def test_product_detail_page_shows_full_fields():
    client, Session_ = _make_client()
    pid, _, _ = _seed_product(Session_, current_status="特價中")
    resp = client.get(f"/products/{pid}")
    assert resp.status_code == 200
    assert f"商品詳細資料 #{pid}" in resp.text
    assert "ASUS RTX 5070 PRIME 12G" in resp.text
    assert "ASUS" in resp.text
    assert "RTX5070-12G" in resp.text
    assert "特價中" in resp.text
    assert "$18,990" in resp.text
    assert "顯示卡VGA" in resp.text
    assert "在售" in resp.text
    assert "2026-02-01" in resp.text


def test_product_detail_page_404_for_missing_product():
    client, _Session_ = _make_client()
    resp = client.get("/products/9999")
    assert resp.status_code == 404


def test_product_detail_page_has_edit_button_and_hidden_edit_form():
    client, Session_ = _make_client()
    pid, _, _ = _seed_product(Session_)
    resp = client.get(f"/products/{pid}")
    assert 'id="editBtn"' in resp.text
    edit_section_pos = resp.text.find('id="editSection"')
    assert edit_section_pos != -1
    assert "hidden" in resp.text[edit_section_pos:edit_section_pos + 40]
    assert f'action="/products/{pid}"' in resp.text
    assert 'name="current_name"' in resp.text
    assert 'id="categorySelect"' in resp.text
    assert 'id="subcategorySelect"' in resp.text
    assert "+ 新增類別" in resp.text


def test_product_update_saves_fields_and_redirects():
    client, Session_ = _make_client()
    pid, cat_id, sub_id = _seed_product(Session_)
    resp = client.post(f"/products/{pid}", data={
        "current_name": "ASUS RTX 5070 PRIME OC 12G",
        "brand": "ASUS",
        "model": "RTX5070-OC-12G",
        "current_status": "現貨",
        "current_price": "19990",
        "category_id": str(cat_id),
        "subcategory_id": str(sub_id),
        "is_active": "false",
    }, follow_redirects=False)
    assert resp.status_code == 303
    assert resp.headers["location"].startswith(f"/products/{pid}?message=")

    with Session_() as session:
        product = session.get(Product, pid)
        assert product.current_name == "ASUS RTX 5070 PRIME OC 12G"
        assert product.model == "RTX5070-OC-12G"
        assert product.current_price == 19990
        assert product.is_active is False


def test_product_update_rejects_subcategory_not_belonging_to_category():
    client, Session_ = _make_client()
    pid, cat_id, sub_id = _seed_product(Session_)
    with Session_() as session:
        other_cat = Category(name="主機板")
        session.add(other_cat)
        session.commit()
        other_cat_id = other_cat.id

    resp = client.post(f"/products/{pid}", data={
        "current_name": "X", "brand": "", "model": "", "current_status": "",
        "current_price": "100", "category_id": str(other_cat_id),
        "subcategory_id": str(sub_id), "is_active": "true",
    })
    assert resp.status_code == 400


def test_product_update_rejects_editing_merged_product():
    client, Session_ = _make_client()
    pid, cat_id, sub_id = _seed_product(Session_)
    with Session_() as session:
        product = session.get(Product, pid)
        product.merged_into_id = pid  # 隨便指到一個已存在的 id 即可觸發「已合併」判斷
        session.commit()

    resp = client.post(f"/products/{pid}", data={
        "current_name": "X", "brand": "", "model": "", "current_status": "",
        "current_price": "100", "category_id": str(cat_id),
        "subcategory_id": str(sub_id), "is_active": "true",
    })
    assert resp.status_code == 400

    detail_resp = client.get(f"/products/{pid}")
    assert "已合併至" in detail_resp.text
    assert 'id="editBtn"' not in detail_resp.text


def test_create_category_creates_category_and_default_subcategory():
    client, Session_ = _make_client()
    resp = client.post("/categories", data={"name": "電源供應器"})
    assert resp.status_code == 200
    data = resp.json()
    assert data["category_label"] == "電源供應器"
    assert data["subcategory_label"] == "電源供應器"

    with Session_() as session:
        category = session.get(Category, data["category_id"])
        assert category.name == "電源供應器"
        subcategory = session.get(Subcategory, data["subcategory_id"])
        assert subcategory.category_id == category.id
        assert subcategory.name == ""


def test_create_category_rejects_duplicate_name():
    client, Session_ = _make_client()
    with Session_() as session:
        session.add(Category(name="電源供應器"))
        session.commit()

    resp = client.post("/categories", data={"name": "電源供應器"})
    assert resp.status_code == 400


def test_create_category_rejects_blank_name():
    client, _Session_ = _make_client()
    resp = client.post("/categories", data={"name": "   "})
    assert resp.status_code == 400
