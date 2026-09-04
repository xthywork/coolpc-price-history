import datetime
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, text
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool
from coolpc.db.models import Base, Category, Subcategory, Product, PriceHistory
from coolpc.public_api.app import app
from coolpc.public_api.dependencies import get_session


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


def test_compare_page_without_ids_shows_form_only():
    client, _ = _make_client()
    resp = client.get("/compare")
    assert resp.status_code == 200
    assert "商品比較" in resp.text


def test_compare_page_shows_error_for_invalid_count():
    client, _ = _make_client()
    resp = client.get("/compare", params={"ids": "1"})
    assert resp.status_code == 200
    assert "請選擇 2 到 5 個商品" in resp.text


def test_compare_page_renders_table_and_chart_for_valid_ids():
    client, Session_ = _make_client()
    t = datetime.datetime(2026, 2, 1)
    with Session_() as session:
        cat = Category(name="顯示卡VGA")
        sub = Subcategory(name="NVIDIA", category=cat)
        session.add_all([cat, sub])
        session.flush()
        p1 = Product(category_id=cat.id, subcategory_id=sub.id, current_name="A卡", current_price=1000,
                     is_active=True, first_seen_at=t, last_seen_at=t, created_at=t)
        p2 = Product(category_id=cat.id, subcategory_id=sub.id, current_name="B卡", current_price=2000,
                     is_active=True, first_seen_at=t, last_seen_at=t, created_at=t)
        session.add_all([p1, p2])
        session.flush()
        session.add(PriceHistory(product_id=p1.id, price=1000, status=None, badges="", scraped_at=t, snapshot_id=1))
        session.add(PriceHistory(product_id=p2.id, price=2000, status=None, badges="", scraped_at=t, snapshot_id=1))
        session.commit()
        id1, id2 = p1.id, p2.id

    resp = client.get("/compare", params={"ids": f"{id1},{id2}"})
    assert resp.status_code == 200
    assert "A卡" in resp.text and "B卡" in resp.text
    assert 'id="compareChart"' in resp.text


def test_compare_page_rejects_merged_away_product_id():
    client, Session_ = _make_client()
    t0 = datetime.datetime(2026, 2, 1)
    t1 = datetime.datetime(2026, 2, 2)
    with Session_() as session:
        cat = Category(name="顯示卡VGA")
        sub = Subcategory(name="NVIDIA", category=cat)
        session.add_all([cat, sub])
        session.flush()
        other = Product(category_id=cat.id, subcategory_id=sub.id, current_name="Other", current_price=300,
                         is_active=True, first_seen_at=t0, last_seen_at=t0, created_at=t0)
        session.add(other)
        session.flush()
        target = Product(category_id=cat.id, subcategory_id=sub.id, current_name="Target", current_price=200,
                          is_active=True, first_seen_at=t0, last_seen_at=t1, created_at=t0)
        session.add(target)
        session.flush()
        source = Product(category_id=cat.id, subcategory_id=sub.id, current_name="Source (merged)",
                          current_price=999, is_active=False, first_seen_at=t0, last_seen_at=t0,
                          created_at=t0, merged_into_id=target.id)
        session.add(source)
        session.flush()
        session.add_all([
            PriceHistory(product_id=source.id, price=999, status=None, badges="", scraped_at=t0, snapshot_id=1),
            PriceHistory(product_id=target.id, price=200, status=None, badges="", scraped_at=t1, snapshot_id=2),
            PriceHistory(product_id=other.id, price=300, status=None, badges="", scraped_at=t0, snapshot_id=1),
        ])
        session.commit()
        source_id, other_id = source.id, other.id

    resp = client.get("/compare", params={"ids": f"{source_id},{other_id}"})
    assert resp.status_code == 200
    assert f"商品不存在: {source_id}" in resp.text


def test_compare_page_table_only_has_four_columns():
    client, Session_ = _make_client()
    t = datetime.datetime(2026, 2, 1)
    with Session_() as session:
        cat = Category(name="顯示卡VGA")
        sub = Subcategory(name="NVIDIA", category=cat)
        session.add_all([cat, sub])
        session.flush()
        p1 = Product(category_id=cat.id, subcategory_id=sub.id, current_name="比較精簡A",
                     current_price=1000, is_active=True, first_seen_at=t, last_seen_at=t, created_at=t)
        p2 = Product(category_id=cat.id, subcategory_id=sub.id, current_name="比較精簡B",
                     current_price=2000, is_active=True, first_seen_at=t, last_seen_at=t, created_at=t)
        session.add_all([p1, p2])
        session.commit()
        p1_id, p2_id = p1.id, p2.id

    resp = client.get("/compare", params={"ids": f"{p1_id},{p2_id}"})
    assert resp.status_code == 200
    assert "7天最低" not in resp.text
    assert "30天最低" not in resp.text
    assert "30天最高" not in resp.text
    assert "最近漲跌" not in resp.text
    assert "歷史最低" in resp.text
    assert "歷史最高" in resp.text
    assert "現價" in resp.text
    # 商品欄要佔表格一半以上寬度，不能被壓縮
    assert 'style="width:55%"' in resp.text
    # 欄寬仍要能手動拖曳調整
    assert "col-resizer" in resp.text
    assert "mousedown" in resp.text


def test_compare_page_has_color_dot_before_product_name_and_no_default_legend():
    client, Session_ = _make_client()
    t = datetime.datetime(2026, 2, 1)
    with Session_() as session:
        cat = Category(name="顯示卡VGA")
        sub = Subcategory(name="NVIDIA", category=cat)
        session.add_all([cat, sub])
        session.flush()
        p1 = Product(category_id=cat.id, subcategory_id=sub.id, current_name="比較顏色A",
                     current_price=1000, is_active=True, first_seen_at=t, last_seen_at=t, created_at=t)
        p2 = Product(category_id=cat.id, subcategory_id=sub.id, current_name="比較顏色B",
                     current_price=2000, is_active=True, first_seen_at=t, last_seen_at=t, created_at=t)
        session.add_all([p1, p2])
        session.commit()
        p1_id, p2_id = p1.id, p2.id

    resp = client.get("/compare", params={"ids": f"{p1_id},{p2_id}"})
    assert resp.status_code == 200
    assert "legend" in resp.text and "display: false" in resp.text.replace('"', '').replace("'", "")
    assert "colors[loop.index0" not in resp.text  # 不應該有殘留的 Jinja 語法字面文字
    assert resp.text.count("background:") >= 2 or resp.text.count("background-color:") >= 2


def test_compare_page_chart_has_range_controls_and_no_apply_button():
    client, Session_ = _make_client()
    t = datetime.datetime(2026, 2, 1)
    with Session_() as session:
        cat = Category(name="顯示卡VGA")
        sub = Subcategory(name="NVIDIA", category=cat)
        session.add_all([cat, sub])
        session.flush()
        p1 = Product(category_id=cat.id, subcategory_id=sub.id, current_name="比較區間A",
                     current_price=1000, is_active=True, first_seen_at=t, last_seen_at=t, created_at=t)
        p2 = Product(category_id=cat.id, subcategory_id=sub.id, current_name="比較區間B",
                     current_price=2000, is_active=True, first_seen_at=t, last_seen_at=t, created_at=t)
        session.add_all([p1, p2])
        session.commit()
        p1_id, p2_id = p1.id, p2.id

    resp = client.get("/compare", params={"ids": f"{p1_id},{p2_id}"})
    assert resp.status_code == 200
    assert 'data-range="7"' in resp.text
    assert 'data-range="30"' in resp.text
    assert 'data-range="90"' in resp.text
    assert 'data-range="all"' in resp.text
    assert 'id="rangeStart"' in resp.text
    assert 'id="rangeEnd"' in resp.text
    assert ">套用<" not in resp.text
    assert "'change'" in resp.text


def test_compare_page_has_clear_link_and_base_html_no_longer_does():
    client, Session_ = _make_client()
    t = datetime.datetime(2026, 2, 1)
    with Session_() as session:
        cat = Category(name="顯示卡VGA")
        sub = Subcategory(name="NVIDIA", category=cat)
        session.add_all([cat, sub])
        session.flush()
        p1 = Product(category_id=cat.id, subcategory_id=sub.id, current_name="比較清空A",
                     current_price=1000, is_active=True, first_seen_at=t, last_seen_at=t, created_at=t)
        p2 = Product(category_id=cat.id, subcategory_id=sub.id, current_name="比較清空B",
                     current_price=2000, is_active=True, first_seen_at=t, last_seen_at=t, created_at=t)
        session.add_all([p1, p2])
        session.commit()
        p1_id, p2_id = p1.id, p2.id

    resp = client.get("/compare", params={"ids": f"{p1_id},{p2_id}"})
    assert resp.status_code == 200
    assert "coolpcCompare.clear()" in resp.text
    assert "清空比較清單" in resp.text

    home = client.get("/")
    assert 'id="compareClearLink"' not in home.text
    # _updateNav 的邏輯（維持已選清單的關鍵）必須還在 base.html 裡，只是清空按鈕搬走
    assert "_updateNav" in home.text
    assert "coolpcCompare" in home.text

    # 死路防護：清單裡有商品失效（例如已合併/下架/不存在）時，/compare 會走
    # error 路徑而不是 items 路徑，清空連結仍必須渲染，否則使用者在清單卡住
    # 5 個且其中一個失效時就永遠無法回復（見 2026-09-03 計畫 final review 的
    # cap-at-5 + clear-list 設計初衷）。
    bad = client.get("/compare", params={"ids": f"{p1_id},{p2_id},999999999"})
    assert bad.status_code == 200
    assert "清空比較清單" in bad.text
