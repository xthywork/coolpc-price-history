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


def test_list_products_filters_by_change_percent_range():
    client, Session_ = _make_client()
    with Session_() as session:
        t = datetime.datetime(2026, 2, 1)
        cat = Category(name="顯示卡VGA")
        sub = Subcategory(name="NVIDIA", category=cat)
        session.add_all([cat, sub])
        session.flush()
        big_jump = Product(category_id=cat.id, subcategory_id=sub.id, current_name="漲很多",
                           current_price=1100, last_change_amount=100, last_change_percent=10.0,
                           is_active=True, first_seen_at=t, last_seen_at=t, created_at=t)
        small_jump = Product(category_id=cat.id, subcategory_id=sub.id, current_name="漲一點點",
                             current_price=1010, last_change_amount=10, last_change_percent=1.0,
                             is_active=True, first_seen_at=t, last_seen_at=t, created_at=t)
        session.add_all([big_jump, small_jump])
        session.commit()

    resp = client.get("/api/products", params={"min_change_percent": 5})
    data = resp.json()
    assert data["total"] == 1
    assert data["items"][0]["current_name"] == "漲很多"


def test_list_products_accepts_blank_optional_query_params_without_422():
    # 前端表單或客戶端組裝查詢字串時常會送出空字串（而非完全省略參數），
    # 例如 category_id=&min_price=&is_active=；這些欄位是 int/bool/float，
    # 必須把空字串視為「未指定」而不是回 422。
    client, _Session_ = _make_client()
    resp = client.get("/api/products", params={
        "q": "", "category_id": "", "subcategory_id": "", "brand": "", "model": "",
        "min_price": "", "max_price": "", "is_active": "", "recent_change": "",
        "min_change_percent": "", "max_change_percent": "",
    })
    assert resp.status_code == 200
    assert resp.json()["total"] == 0
