import datetime
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool
from coolpc.db.models import Base, Category, Subcategory, Product, SimilarityHint, MergeLog
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


def test_similarity_hints_page_lists_candidates():
    client, Session_ = _make_client()
    t = datetime.datetime(2026, 2, 1)
    with Session_() as session:
        cat = Category(name="顯示卡VGA")
        sub = Subcategory(name="NVIDIA", category=cat)
        session.add_all([cat, sub])
        session.flush()
        a = Product(category_id=cat.id, subcategory_id=sub.id, current_name="ASUS RTX 5070 PRIME 12G",
                   current_price=100, is_active=False, last_seen_at=t, created_at=t)
        b = Product(category_id=cat.id, subcategory_id=sub.id, current_name="ASUS RTX 5070 PRIME OC 12GB",
                   current_price=200, is_active=True, last_seen_at=t, created_at=t)
        session.add_all([a, b])
        session.flush()
        session.add(SimilarityHint(product_a_id=a.id, product_b_id=b.id, score=0.85,
                                    computed_at=t, dismissed=False))
        session.commit()

    resp = client.get("/similarity-hints")
    assert resp.status_code == 200
    assert "ASUS RTX 5070 PRIME 12G" in resp.text
    assert ">85</span>" in resp.text and "相似度 %" in resp.text


def test_similarity_hints_refresh_creates_new_hints():
    client, Session_ = _make_client()
    t = datetime.datetime(2026, 2, 1)
    with Session_() as session:
        cat = Category(name="顯示卡VGA")
        sub = Subcategory(name="NVIDIA", category=cat)
        session.add_all([cat, sub])
        session.flush()
        a = Product(category_id=cat.id, subcategory_id=sub.id, current_name="ASUS RTX 5070 PRIME 12G",
                   current_price=100, is_active=False, last_seen_at=t, created_at=t)
        b = Product(category_id=cat.id, subcategory_id=sub.id, current_name="ASUS RTX 5070 PRIME OC 12GB",
                   current_price=200, is_active=True, last_seen_at=t, created_at=t)
        session.add_all([a, b])
        session.commit()

    resp = client.post("/similarity-hints/refresh", follow_redirects=False)
    assert resp.status_code == 303
    resp2 = client.get("/similarity-hints")
    assert "ASUS RTX 5070 PRIME 12G" in resp2.text


def test_dismiss_hint_removes_it_from_list():
    client, Session_ = _make_client()
    t = datetime.datetime(2026, 2, 1)
    with Session_() as session:
        cat = Category(name="顯示卡VGA")
        sub = Subcategory(name="NVIDIA", category=cat)
        session.add_all([cat, sub])
        session.flush()
        a = Product(category_id=cat.id, subcategory_id=sub.id, current_name="商品A獨特字串",
                   current_price=100, is_active=True, last_seen_at=t, created_at=t)
        b = Product(category_id=cat.id, subcategory_id=sub.id, current_name="商品B獨特字串",
                   current_price=200, is_active=True, last_seen_at=t, created_at=t)
        session.add_all([a, b])
        session.flush()
        hint = SimilarityHint(product_a_id=a.id, product_b_id=b.id, score=0.8, computed_at=t, dismissed=False)
        session.add(hint)
        session.commit()
        hint_id = hint.id

    before = client.get("/similarity-hints")
    assert "商品A獨特字串" in before.text

    resp = client.post(f"/similarity-hints/{hint_id}/dismiss", follow_redirects=False)
    assert resp.status_code == 303
    after = client.get("/similarity-hints")
    assert "商品A獨特字串" not in after.text


def test_batch_merge_hints_merges_selected_pairs_and_dismisses_their_hints():
    client, Session_ = _make_client()
    t = datetime.datetime(2026, 2, 1)
    with Session_() as session:
        cat = Category(name="顯示卡VGA")
        sub = Subcategory(name="NVIDIA", category=cat)
        session.add_all([cat, sub])
        session.flush()
        a = Product(category_id=cat.id, subcategory_id=sub.id, current_name="舊名稱下架商品",
                   current_price=100, is_active=False, last_seen_at=t, created_at=t)
        b = Product(category_id=cat.id, subcategory_id=sub.id, current_name="新名稱在售商品",
                   current_price=200, is_active=True, last_seen_at=t, created_at=t)
        session.add_all([a, b])
        session.flush()
        hint = SimilarityHint(product_a_id=a.id, product_b_id=b.id, score=0.9,
                               computed_at=t, dismissed=False)
        session.add(hint)
        session.commit()
        hint_id, a_id, b_id = hint.id, a.id, b.id

    resp = client.post("/similarity-hints/batch-merge", data={"hint_ids": [hint_id]},
                        follow_redirects=False)
    assert resp.status_code == 303

    with Session_() as session:
        a_after = session.get(Product, a_id)
        b_after = session.get(Product, b_id)
        # a 已下架、b 仍在售 -> a 是 source（被合併掉）、b 是 target（保留）
        assert a_after.merged_into_id == b_id
        assert b_after.merged_into_id is None
        hint_after = session.get(SimilarityHint, hint_id)
        assert hint_after.dismissed is True
        logs = session.query(MergeLog).filter_by(source_product_id=a_id, target_product_id=b_id).all()
        assert len(logs) == 1


def test_batch_dismiss_hints_dismisses_selected_without_merging():
    client, Session_ = _make_client()
    t = datetime.datetime(2026, 2, 1)
    with Session_() as session:
        cat = Category(name="顯示卡VGA")
        sub = Subcategory(name="NVIDIA", category=cat)
        session.add_all([cat, sub])
        session.flush()
        a = Product(category_id=cat.id, subcategory_id=sub.id, current_name="商品A獨特字串批量忽略",
                   current_price=100, is_active=True, last_seen_at=t, created_at=t)
        b = Product(category_id=cat.id, subcategory_id=sub.id, current_name="商品B獨特字串批量忽略",
                   current_price=200, is_active=True, last_seen_at=t, created_at=t)
        session.add_all([a, b])
        session.flush()
        hint = SimilarityHint(product_a_id=a.id, product_b_id=b.id, score=0.8,
                               computed_at=t, dismissed=False)
        session.add(hint)
        session.commit()
        hint_id, a_id, b_id = hint.id, a.id, b.id

    resp = client.post("/similarity-hints/batch-dismiss", data={"hint_ids": [hint_id]},
                        follow_redirects=False)
    assert resp.status_code == 303

    with Session_() as session:
        a_after = session.get(Product, a_id)
        b_after = session.get(Product, b_id)
        assert a_after.merged_into_id is None
        assert b_after.merged_into_id is None

    after = client.get("/similarity-hints")
    assert "商品A獨特字串批量忽略" not in after.text


def test_similarity_hints_excludes_merged_away_products_beyond_naive_limit():
    """在 LIMIT 100 之前先在 SQL 排除已合併商品的候選配對——若還是先 LIMIT 100
    再用 Python 過濾，分數最高但已失效的那組會佔掉 LIMIT 視窗裡的一個名額，
    導致排在它後面、分數較低但仍然有效的候選被擠出畫面（總數少於 100）。"""
    client, Session_ = _make_client()
    t = datetime.datetime(2026, 2, 1)
    with Session_() as session:
        cat = Category(name="顯示卡VGA")
        sub = Subcategory(name="NVIDIA", category=cat)
        session.add_all([cat, sub])
        session.flush()

        # 分數最高、但其中一個商品已被合併走的失效候選。
        merged_a = Product(category_id=cat.id, subcategory_id=sub.id, current_name="已合併商品A",
                            current_price=100, is_active=False, last_seen_at=t, created_at=t)
        merged_b = Product(category_id=cat.id, subcategory_id=sub.id, current_name="已合併商品B",
                            current_price=200, is_active=True, last_seen_at=t, created_at=t)
        session.add_all([merged_a, merged_b])
        session.flush()
        merged_a.merged_into_id = merged_b.id
        session.add(SimilarityHint(product_a_id=merged_a.id, product_b_id=merged_b.id,
                                    score=0.99, computed_at=t, dismissed=False))

        # 101 組分數較低、但仍然有效的候選配對。
        for i in range(101):
            pa = Product(category_id=cat.id, subcategory_id=sub.id, current_name=f"有效商品A{i}",
                         current_price=100, is_active=True, last_seen_at=t, created_at=t)
            pb = Product(category_id=cat.id, subcategory_id=sub.id, current_name=f"有效商品B{i}",
                         current_price=200, is_active=True, last_seen_at=t, created_at=t)
            session.add_all([pa, pb])
            session.flush()
            session.add(SimilarityHint(product_a_id=pa.id, product_b_id=pb.id,
                                        score=0.5 + i * 0.001, computed_at=t, dismissed=False))
        session.commit()

    resp = client.get("/similarity-hints")
    assert resp.status_code == 200
    assert "已合併商品A" not in resp.text
    assert "已合併商品B" not in resp.text
    # 應該顯示滿滿 100 組真正待處理的候選，不會因為失效項目佔用 LIMIT 名額而變少。
    assert resp.text.count('name="hint_ids"') == 100


def test_similarity_hints_page_has_checkbox_and_no_per_row_action_column():
    client, Session_ = _make_client()
    t = datetime.datetime(2026, 2, 1)
    with Session_() as session:
        cat = Category(name="顯示卡VGA")
        sub = Subcategory(name="NVIDIA", category=cat)
        session.add_all([cat, sub])
        session.flush()
        a = Product(category_id=cat.id, subcategory_id=sub.id, current_name="核取方塊測試A",
                   current_price=100, is_active=True, last_seen_at=t, created_at=t)
        b = Product(category_id=cat.id, subcategory_id=sub.id, current_name="核取方塊測試B",
                   current_price=200, is_active=True, last_seen_at=t, created_at=t)
        session.add_all([a, b])
        session.flush()
        hint = SimilarityHint(product_a_id=a.id, product_b_id=b.id, score=0.8,
                               computed_at=t, dismissed=False)
        session.add(hint)
        session.commit()
        hint_id = hint.id

    resp = client.get("/similarity-hints")
    assert resp.status_code == 200
    assert f'name="hint_ids" value="{hint_id}"' in resp.text
    # 按鈕文字不再有「批量」二字與括號說明
    assert ">合併勾選的<" in resp.text
    assert ">忽略勾選的<" in resp.text
    assert "批量" not in resp.text
    # 舊版每列一個「不是同一商品，忽略」的獨立表單已移除
    assert "不是同一商品，忽略" not in resp.text


def test_similarity_hints_page_stacks_products_vertically_with_score_beside_and_group_separation():
    """商品 A / 商品 B 要一個一列（上下堆疊），不是左右分欄；相似度顯示在
    整組旁邊；每組候選（card）之間要有清楚的視覺分隔，方便快速比對合併。"""
    client, Session_ = _make_client()
    t = datetime.datetime(2026, 2, 1)
    with Session_() as session:
        cat = Category(name="顯示卡VGA")
        sub = Subcategory(name="NVIDIA", category=cat)
        session.add_all([cat, sub])
        session.flush()
        a = Product(category_id=cat.id, subcategory_id=sub.id, current_name="堆疊排版測試A",
                   current_price=100, is_active=True, last_seen_at=t, created_at=t)
        b = Product(category_id=cat.id, subcategory_id=sub.id, current_name="堆疊排版測試B",
                   current_price=200, is_active=True, last_seen_at=t, created_at=t)
        session.add_all([a, b])
        session.flush()
        hint = SimilarityHint(product_a_id=a.id, product_b_id=b.id, score=0.8,
                               computed_at=t, dismissed=False)
        session.add(hint)
        session.commit()

    resp = client.get("/similarity-hints")
    assert resp.status_code == 200
    # 不再是表格版面
    assert "<table>" not in resp.text
    assert "<thead>" not in resp.text
    # 一組（card）裡，商品 A 的整行要先於商品 B 的整行出現（上下堆疊），
    # 且兩者之間要有一個分隔元素。用帶引號的 class="..." 屬性字串比對，
    # 確保比對到的是實際的 <div> 元素，不是誤中前面 CSS 的 .hintDivider 選
    # 擇器（CSS 定義本來就寫在所有卡片內容之前，跟畫面上的實際順序無關）。
    a_row_pos = resp.text.find("堆疊排版測試A")
    divider_pos = resp.text.find('class="hint__sep"')
    b_row_pos = resp.text.find("堆疊排版測試B")
    assert a_row_pos != -1 and divider_pos != -1 and b_row_pos != -1
    assert a_row_pos < divider_pos < b_row_pos
    # 相似度要在同一組（card）內，顯示在商品旁邊，而不是獨立的表格欄位
    assert "hint__score" in resp.text
    assert 'class="hint"' in resp.text


def test_similarity_hints_page_has_merge_all_button_with_confirm_and_reuses_batch_merge_endpoint():
    """「合併下列所有項目」要送到既有的 /similarity-hints/batch-merge（沿用同一套
    後端邏輯，不需要新路由），點擊時要先跳出確認對話框，確認後才把畫面上
    所有候選的核取方塊全部勾選再送出——不是只送目前手動勾選的那幾組。"""
    client, Session_ = _make_client()
    t = datetime.datetime(2026, 2, 1)
    with Session_() as session:
        cat = Category(name="顯示卡VGA")
        sub = Subcategory(name="NVIDIA", category=cat)
        session.add_all([cat, sub])
        session.flush()
        a = Product(category_id=cat.id, subcategory_id=sub.id, current_name="全部合併測試A",
                   current_price=100, is_active=True, last_seen_at=t, created_at=t)
        b = Product(category_id=cat.id, subcategory_id=sub.id, current_name="全部合併測試B",
                   current_price=200, is_active=True, last_seen_at=t, created_at=t)
        session.add_all([a, b])
        session.flush()
        hint = SimilarityHint(product_a_id=a.id, product_b_id=b.id, score=0.8,
                               computed_at=t, dismissed=False)
        session.add(hint)
        session.commit()

    resp = client.get("/similarity-hints")
    assert resp.status_code == 200
    assert '<button type="submit" formaction="/similarity-hints/batch-merge" id="mergeAllBtn">合併全部候選</button>' in resp.text
    assert "confirm(" in resp.text
    assert "cb.checked = true" in resp.text
