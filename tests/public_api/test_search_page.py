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


def test_search_page_shows_category_display_name_when_set():
    client, Session_ = _make_client()
    t = datetime.datetime(2026, 2, 1)
    with Session_() as session:
        cat = Category(name="顯示卡VGA", display_name="顯卡")
        sub = Subcategory(name="NVIDIA", category=cat)
        session.add_all([cat, sub])
        session.flush()
        p = Product(category_id=cat.id, subcategory_id=sub.id, current_name="顯示名稱測試商品",
                    current_price=1000, is_active=True, first_seen_at=t, last_seen_at=t, created_at=t)
        session.add(p)
        session.flush()
        session.add(ProductName(product_id=p.id, name=p.current_name, first_seen_at=t, last_seen_at=t))
        session.commit()

    resp = client.get("/")
    assert resp.status_code == 200
    assert "顯卡 / NVIDIA" in resp.text
    assert "<td>顯卡</td>" in resp.text
    assert "顯示卡VGA" not in resp.text


def test_search_page_subcategory_dropdown_respects_category_sort_order():
    client, Session_ = _make_client()
    t = datetime.datetime(2026, 2, 1)
    with Session_() as session:
        # 刻意讓 name 的字母順序跟 sort_order 相反，證明真的是照 sort_order排
        cat_a = Category(name="Z分類", sort_order=2)
        sub_a = Subcategory(name="子A", category=cat_a)
        cat_b = Category(name="A分類", sort_order=1)
        sub_b = Subcategory(name="子B", category=cat_b)
        cat_c = Category(name="M分類")  # sort_order 未設定，應排最後
        sub_c = Subcategory(name="子C", category=cat_c)
        session.add_all([cat_a, sub_a, cat_b, sub_b, cat_c, sub_c])
        session.commit()

    resp = client.get("/")
    assert resp.status_code == 200
    pos_a = resp.text.find("A分類 / 子B")
    pos_b = resp.text.find("Z分類 / 子A")
    pos_c = resp.text.find("M分類 / 子C")
    assert pos_a != -1 and pos_b != -1 and pos_c != -1
    assert pos_a < pos_b < pos_c


def test_search_page_dropdown_hides_trailing_slash_when_subcategory_name_is_blank():
    # 原價屋許多分類本身沒有第二層子分類，實際資料是一筆名稱為空字串的
    # 子分類；下拉選單只該顯示分類名稱，不能留下「分類 / 」這種空尾巴。
    client, Session_ = _make_client()
    with Session_() as session:
        cat = Category(name="無子分類測試")
        sub = Subcategory(name="", category=cat)
        session.add_all([cat, sub])
        session.commit()

    resp = client.get("/")
    assert resp.status_code == 200
    assert ">無子分類測試</option>" in resp.text
    assert "無子分類測試 / " not in resp.text


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


def test_search_page_recent_change_select_removed_and_sort_options_reduced():
    client, _Session_ = _make_client()
    resp = client.get("/")
    assert resp.status_code == 200
    assert 'name="recent_change"' not in resp.text
    assert "最近漲價" not in resp.text
    assert "最近降價" not in resp.text
    assert 'value="last_seen_desc"' not in resp.text
    assert 'value="name_asc"' not in resp.text
    assert 'value="price_asc"' in resp.text
    assert 'value="price_desc"' in resp.text
    assert 'value="brand_asc"' in resp.text
    assert 'value="category_asc"' in resp.text
    assert 'value="status_active_first"' in resp.text


def test_base_layout_has_compare_clear_control():
    # 「清空比較清單」連結已搬到 /compare 頁面本身（見 test_compare_page.py），
    # base.html（所有頁面共用）不應該再有這個控制項；coolpcCompare.clear() 方法本身仍保留。
    client, _Session_ = _make_client()
    resp = client.get("/")
    assert resp.status_code == 200
    assert 'id="compareClearLink"' not in resp.text
    assert "clear()" in resp.text


def test_base_layout_compare_js_has_cap_at_5_logic_and_clear_method():
    client, _Session_ = _make_client()
    resp = client.get("/")
    assert resp.status_code == 200
    # cap-at-5：加入前檢查目前清單長度，達到 5 個時拒絕加入並跳出提示
    assert "ids.length >= 5" in resp.text
    assert "比較清單最多 5 個商品" in resp.text
    # clear() 方法：清空清單並更新導覽列
    assert "clear() {" in resp.text
    assert "this._write([]);" in resp.text


def test_search_page_results_table_only_has_four_columns_plus_checkbox():
    client, Session_ = _make_client()
    t = datetime.datetime(2026, 2, 1)
    with Session_() as session:
        cat = Category(name="顯示卡VGA")
        sub = Subcategory(name="NVIDIA", category=cat)
        session.add_all([cat, sub])
        session.flush()
        p = Product(category_id=cat.id, subcategory_id=sub.id, current_name="表格精簡測試",
                   current_price=18990, is_active=True, first_seen_at=t, last_seen_at=t, created_at=t)
        session.add(p)
        session.flush()
        session.add(ProductName(product_id=p.id, name=p.current_name, first_seen_at=t, last_seen_at=t))
        session.commit()
        product_id = p.id

    resp = client.get("/")
    assert resp.status_code == 200
    assert "上次價格" not in resp.text
    assert "漲跌</th>" not in resp.text
    assert "30天最低" not in resp.text
    assert "30天最高" not in resp.text
    assert "<th>最後更新</th>" not in resp.text
    assert "商品名稱" in resp.text
    assert "分類" in resp.text
    assert "狀態" in resp.text
    # 商品名稱欄要佔表格一半以上寬度，不能被壓縮
    assert 'style="width:55%"' in resp.text
    assert f'data-id="{product_id}"' in resp.text
    assert 'class="compareCheckbox"' in resp.text


def test_search_page_shows_global_last_updated_after_result_count():
    client, Session_ = _make_client()
    t1 = datetime.datetime(2026, 1, 1, 12, 0)
    t2 = datetime.datetime(2026, 2, 1, 18, 0)
    with Session_() as session:
        cat = Category(name="顯示卡VGA")
        sub = Subcategory(name="NVIDIA", category=cat)
        session.add_all([cat, sub])
        session.flush()
        p1 = Product(category_id=cat.id, subcategory_id=sub.id, current_name="更新時間A",
                    current_price=1000, is_active=True, first_seen_at=t1, last_seen_at=t1, created_at=t1)
        p2 = Product(category_id=cat.id, subcategory_id=sub.id, current_name="更新時間B",
                    current_price=2000, is_active=True, first_seen_at=t2, last_seen_at=t2, created_at=t2)
        session.add_all([p1, p2])
        session.commit()

    resp = client.get("/")
    assert resp.status_code == 200
    count_pos = resp.text.find("共 2 筆結果")
    updated_pos = resp.text.find("最後更新")
    assert count_pos != -1
    assert updated_pos != -1
    assert updated_pos > count_pos
    assert "2026-02-01 18:00" in resp.text  # 兩者取較新的 t2


def test_search_page_table_is_resizable():
    client, _Session_ = _make_client()
    resp = client.get("/")
    assert resp.status_code == 200
    assert "col-resizer" in resp.text
    assert "mousedown" in resp.text
