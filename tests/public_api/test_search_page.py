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


def test_search_page_subcategory_select_and_filter():
    client, Session_ = _make_client()
    t = datetime.datetime(2026, 2, 1)
    with Session_() as session:
        cat1 = Category(name="顯示卡VGA")
        sub1 = Subcategory(name="NVIDIA", category=cat1)
        cat2 = Category(name="主機板MB")
        sub2 = Subcategory(name="ASUS", category=cat2)
        session.add_all([cat1, sub1, cat2, sub2])
        session.flush()

        p1 = Product(category_id=cat1.id, subcategory_id=sub1.id, current_name="顯卡商品A",
                      current_price=10000, is_active=True, first_seen_at=t, last_seen_at=t, created_at=t)
        p2 = Product(category_id=cat2.id, subcategory_id=sub2.id, current_name="主機板商品B",
                      current_price=5000, is_active=True, first_seen_at=t, last_seen_at=t, created_at=t)
        session.add_all([p1, p2])
        session.flush()
        session.add(ProductName(product_id=p1.id, name=p1.current_name, first_seen_at=t, last_seen_at=t))
        session.add(ProductName(product_id=p2.id, name=p2.current_name, first_seen_at=t, last_seen_at=t))
        session.commit()
        sub1_id = sub1.id

    # 未篩選：頁面應列出兩個子分類選項，且兩個商品都出現
    resp = client.get("/")
    assert resp.status_code == 200
    assert "顯示卡VGA / NVIDIA" in resp.text
    assert "主機板MB / ASUS" in resp.text
    assert "顯卡商品A" in resp.text
    assert "主機板商品B" in resp.text

    # 依 subcategory_id 篩選：結果只剩該子分類的商品，且該選項被標記 selected
    resp = client.get("/", params={"subcategory_id": sub1_id})
    assert resp.status_code == 200
    assert "顯卡商品A" in resp.text
    assert "主機板商品B" not in resp.text
    assert f'value="{sub1_id}" selected' in resp.text


def test_search_page_accepts_blank_form_fields_without_422():
    # 瀏覽器送出未填的下拉選單/數字欄位時，值是空字串而非省略整個參數
    # （例如 category_id=&min_price=&is_active=&min_change_percent=），
    # 這些欄位型別是 int/bool/float，必須把空字串視為「未指定」而不是 422。
    client, _Session_ = _make_client()
    resp = client.get("/", params={
        "q": "", "category_id": "", "subcategory_id": "", "brand": "", "model": "",
        "min_price": "", "max_price": "", "is_active": "", "recent_change": "",
        "min_change_percent": "", "max_change_percent": "", "sort": "last_seen_desc",
    })
    assert resp.status_code == 200


def test_search_page_brand_is_dropdown_populated_from_existing_brands():
    client, Session_ = _make_client()
    t = datetime.datetime(2026, 2, 1)
    with Session_() as session:
        cat = Category(name="顯示卡VGA")
        sub = Subcategory(name="NVIDIA", category=cat)
        session.add_all([cat, sub])
        session.flush()
        p = Product(category_id=cat.id, subcategory_id=sub.id, current_name="ASUS RTX 5070",
                   brand="ASUS", current_price=18990, is_active=True,
                   first_seen_at=t, last_seen_at=t, created_at=t)
        session.add(p)
        session.commit()

    resp = client.get("/")
    assert resp.status_code == 200
    assert '<select name="brand"' in resp.text
    assert 'type="text" name="brand"' not in resp.text
    assert '<option value="ASUS"' in resp.text


def test_search_page_removed_fields_are_gone():
    client, _Session_ = _make_client()
    resp = client.get("/")
    assert resp.status_code == 200
    assert 'name="category_id"' not in resp.text
    assert 'name="model"' not in resp.text
    assert 'name="min_change_percent"' not in resp.text
    assert 'name="max_change_percent"' not in resp.text
    assert 'name="subcategory_id"' in resp.text
