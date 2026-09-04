import datetime
from pathlib import Path
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
                    current_price=18990, is_active=True, last_seen_at=t, created_at=t)
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
                        current_price=1000 + i, is_active=True, last_seen_at=t, created_at=t)
            session.add(p)
            session.flush()
            session.add(ProductName(product_id=p.id, name=name, first_seen_at=t, last_seen_at=t))
        session.commit()

    resp = client.get("/", params={"sort": "price_desc", "page": 1})
    assert resp.status_code == 200
    assert "sort=price_desc" in resp.text
    assert "page=2" in resp.text


def test_search_page_default_page_size_is_twenty_and_shown_selected():
    client, Session_ = _make_client()
    t = datetime.datetime(2026, 2, 1)
    with Session_() as session:
        cat = Category(name="顯示卡VGA")
        sub = Subcategory(name="NVIDIA", category=cat)
        session.add_all([cat, sub])
        session.flush()
        for i in range(25):
            name = f"ASUS 分頁測試{i}"
            p = Product(category_id=cat.id, subcategory_id=sub.id, current_name=name,
                        current_price=1000 + i, is_active=True, last_seen_at=t, created_at=t)
            session.add(p)
            session.flush()
            session.add(ProductName(product_id=p.id, name=name, first_seen_at=t, last_seen_at=t))
        session.commit()

    resp = client.get("/")
    assert resp.status_code == 200
    # 預設每頁 20 筆，25 筆資料應該分成 2 頁，且下拉選單要正確標示目前選的是 20
    assert 'value="20" selected' in resp.text
    assert resp.text.count("ASUS 分頁測試") == 20
    assert 'id="jumpPageInput"' in resp.text
    assert 'max="2"' in resp.text


def test_search_page_page_size_all_shows_every_result_on_one_page():
    client, Session_ = _make_client()
    t = datetime.datetime(2026, 2, 1)
    with Session_() as session:
        cat = Category(name="顯示卡VGA")
        sub = Subcategory(name="NVIDIA", category=cat)
        session.add_all([cat, sub])
        session.flush()
        for i in range(25):
            name = f"ASUS 全部顯示測試{i}"
            p = Product(category_id=cat.id, subcategory_id=sub.id, current_name=name,
                        current_price=1000 + i, is_active=True, last_seen_at=t, created_at=t)
            session.add(p)
            session.flush()
            session.add(ProductName(product_id=p.id, name=name, first_seen_at=t, last_seen_at=t))
        session.commit()

    resp = client.get("/", params={"page_size": "all"})
    assert resp.status_code == 200
    assert resp.text.count("ASUS 全部顯示測試") == 25
    assert 'value="all" selected' in resp.text
    assert 'max="1"' in resp.text  # 全部顯示只有一頁


def test_search_page_pagination_shows_numbered_page_links_and_jump_control():
    client, Session_ = _make_client()
    t = datetime.datetime(2026, 2, 1)
    with Session_() as session:
        cat = Category(name="顯示卡VGA")
        sub = Subcategory(name="NVIDIA", category=cat)
        session.add_all([cat, sub])
        session.flush()
        for i in range(45):
            name = f"ASUS 頁碼測試{i}"
            p = Product(category_id=cat.id, subcategory_id=sub.id, current_name=name,
                        current_price=1000 + i, is_active=True, last_seen_at=t, created_at=t)
            session.add(p)
            session.flush()
            session.add(ProductName(product_id=p.id, name=name, first_seen_at=t, last_seen_at=t))
        session.commit()

    # 45 筆、每頁 10 筆 -> 5 頁，應該可以直接連到第 3、第 5 頁（不是只有上一頁/下一頁）
    resp = client.get("/", params={"page_size": "10", "page": 1})
    assert resp.status_code == 200
    assert "page=3" in resp.text
    assert "page=5" in resp.text
    assert 'id="jumpPageInput"' in resp.text
    assert 'max="5"' in resp.text


def test_search_page_pagination_is_centered_no_go_button_page_size_beside_total_pages():
    client, _Session_ = _make_client()
    resp = client.get("/")
    assert resp.status_code == 200
    # 頁碼控制列的排版交給 pagination__pages（樣式在 base.css，不再寫 inline）
    assert 'class="pagination__pages"' in resp.text
    # 「前往」按鈕已刪除，改成 Enter 直接跳頁
    assert 'id="jumpPageBtn"' not in resp.text
    assert ">前往<" not in resp.text
    assert "e.key !== 'Enter'" in resp.text
    # 跳頁輸入框數字置中
    css = (Path(__file__).parents[2] / "src/coolpc/web/static/css/base.css").read_text(encoding="utf-8")
    assert ".pagination__jump input { width: 64px; text-align: center; }" in css
    # 每頁筆數下拉選單要在總頁數文字右側，且不在最上面的篩選表單裡
    # （用 form="searchFiltersForm" 關聯回原本的表單，本身不在 <form> 標籤內）
    total_pages_pos = resp.text.find("／ 1 頁")
    page_size_pos = resp.text.find('id="pageSizeSelect"')
    assert total_pages_pos != -1 and page_size_pos != -1
    assert total_pages_pos < page_size_pos
    assert 'form="searchFiltersForm"' in resp.text


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
                      current_price=10000, is_active=True, last_seen_at=t, created_at=t)
        p2 = Product(category_id=cat2.id, subcategory_id=sub2.id, current_name="主機板商品B",
                      current_price=5000, is_active=True, last_seen_at=t, created_at=t)
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
                    current_price=1000, is_active=True, last_seen_at=t, created_at=t)
        session.add(p)
        session.flush()
        session.add(ProductName(product_id=p.id, name=p.current_name, first_seen_at=t, last_seen_at=t))
        session.commit()

    resp = client.get("/")
    assert resp.status_code == 200
    assert "顯卡 / NVIDIA" in resp.text
    assert 'class="cat">顯卡' in resp.text
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
    # （例如 category_id=&min_price=&is_active=），這些欄位型別是
    # int/bool/float，必須把空字串視為「未指定」而不是 422。
    client, _Session_ = _make_client()
    resp = client.get("/", params={
        "q": "", "category_id": "", "subcategory_id": "", "brand": "", "model": "",
        "min_price": "", "max_price": "", "is_active": "", "sort": "last_seen_desc",
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
                   last_seen_at=t, created_at=t)
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


def test_search_page_price_inputs_moved_last_to_own_row_with_auto_submit():
    client, _Session_ = _make_client()
    resp = client.get("/")
    assert resp.status_code == 200
    # 最低/最高價格排在其他欄位之後
    pos_sort = resp.text.find('name="sort"')
    pos_min_price = resp.text.find('id="minPriceInput"')
    pos_max_price = resp.text.find('id="maxPriceInput"')
    assert pos_sort != -1 and pos_min_price != -1 and pos_max_price != -1
    assert pos_sort < pos_min_price < pos_max_price
    # 搜尋按鈕在第一行（價格欄位之前），只送出第一行欄位仍在同一個 form 內
    pos_button = resp.text.find(">搜尋</button>")
    assert pos_button != -1
    assert pos_button < pos_min_price
    # 價格欄位變動要用 /api/products 局部重繪表格（不是 ?q= 整頁導頁式更新，
    # 也不是呼叫 form.submit() 整頁 reload）——只確認「價格 debounce」那段函式
    # 本身沒有呼叫 submit()，頁面上其他控制項（例如每頁筆數下拉選單）另外
    # 用真正的整頁 reload 是合理、預期中的行為，不受這裡限制。
    assert "minPriceInput" in resp.text and "addEventListener" in resp.text
    assert "/api/products?" in resp.text
    assert "resultCount" in resp.text


def test_search_page_keyword_input_wide_button_beside_it_dropdowns_on_next_row():
    client, _Session_ = _make_client()
    resp = client.get("/")
    assert resp.status_code == 200
    # 關鍵字輸入框變寬（flex:1），搜尋按鈕緊接在它右側，不再用 margin-left:auto
    # 靠右對齊
    pos_q = resp.text.find('name="q"')
    pos_button = resp.text.find(">搜尋</button>")
    pos_subcategory = resp.text.find('name="subcategory_id"')
    assert pos_q != -1 and pos_button != -1 and pos_subcategory != -1
    assert pos_q < pos_button < pos_subcategory
    # 輸入框吃滿剩餘寬度，改由 public.css 負責，不再寫 inline style
    css = (Path(__file__).parents[2] / "src/coolpc/web/static/css/public.css").read_text(encoding="utf-8")
    assert ".search-head__row input[type=\"text\"] {" in css
    assert "flex: 1;" in css
    assert "margin-left:auto" not in resp.text
    autoupdate_start = resp.text.find("function autoUpdatePriceFilter")
    autoupdate_end = resp.text.find("})();", autoupdate_start)
    assert autoupdate_start != -1 and autoupdate_end != -1
    assert ".submit()" not in resp.text[autoupdate_start:autoupdate_end]


def test_search_page_preserves_scroll_position_across_page_size_change():
    client, _Session_ = _make_client()
    resp = client.get("/")
    assert resp.status_code == 200
    # 改變每頁筆數時，先把目前捲動位置存到 sessionStorage，再送出表單
    change_start = resp.text.find("pageSizeSelect.addEventListener('change'")
    change_end = resp.text.find("});", change_start)
    assert change_start != -1 and change_end != -1
    handler_body = resp.text[change_start:change_end]
    assert "sessionStorage.setItem('coolpc_search_scroll'" in handler_body
    assert "window.scrollY" in handler_body
    assert ".submit()" in handler_body
    # 還原捲動位置的程式必須放在表格/分頁的 HTML 都解析完之後才執行，這樣
    # 頁面才有足夠高度可以捲過去；放在內容最前面同步執行的話，執行當下後面
    # 的表格還沒被瀏覽器解析出來，頁面還很短，scrollTo 到的位置形同無效。
    restore_pos = resp.text.find("sessionStorage.getItem('coolpc_search_scroll')")
    pagination_pos = resp.text.find('class="pagination"')
    assert restore_pos != -1 and pagination_pos != -1
    assert restore_pos > pagination_pos
    assert "window.scrollTo(0, parseInt(savedScroll, 10))" in resp.text


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
                   current_price=18990, is_active=True, last_seen_at=t, created_at=t)
        session.add(p)
        session.flush()
        session.add(ProductName(product_id=p.id, name=p.current_name, first_seen_at=t, last_seen_at=t))
        session.commit()
        product_id = p.id

    resp = client.get("/")
    assert resp.status_code == 200
    # 表格維持精簡：舊版那幾個統計欄位都不該回來
    assert "上次價格" not in resp.text
    assert "30天最低" not in resp.text
    assert "30天最高" not in resp.text
    assert "<th>最後更新</th>" not in resp.text
    # 欄位就是這五個：商品、走勢、價格、區間漲跌、比較勾選
    thead = resp.text[resp.text.find("<thead>"):resp.text.find("</thead>")]
    assert thead.count("</th>") == 5
    for header in (">商品<", ">走勢<", ">價格<", ">區間漲跌<", ">比較<"):
        assert header in thead
    # 分類與下架狀態併進商品欄，不再各佔一欄
    assert 'class="cat"' in resp.text
    # 商品欄是唯一沒有固定寬度的欄，才吃得到剩下的所有寬度
    assert "<th>商品</th>" in thead
    assert thead.count("col-spark") == 1
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
                    current_price=1000, is_active=True, last_seen_at=t1, created_at=t1)
        p2 = Product(category_id=cat.id, subcategory_id=sub.id, current_name="更新時間B",
                    current_price=2000, is_active=True, last_seen_at=t2, created_at=t2)
        session.add_all([p1, p2])
        session.commit()

    resp = client.get("/")
    assert resp.status_code == 200
    assert '<strong id="resultCount">2</strong>' in resp.text
    count_pos = resp.text.find('id="resultCount"')
    updated_pos = resp.text.find("資料更新於")
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
