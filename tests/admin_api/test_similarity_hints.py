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
                   current_price=100, is_active=False, first_seen_at=t, last_seen_at=t, created_at=t)
        b = Product(category_id=cat.id, subcategory_id=sub.id, current_name="ASUS RTX 5070 PRIME OC 12GB",
                   current_price=200, is_active=True, first_seen_at=t, last_seen_at=t, created_at=t)
        session.add_all([a, b])
        session.flush()
        session.add(SimilarityHint(product_a_id=a.id, product_b_id=b.id, score=0.85,
                                    computed_at=t, dismissed=False))
        session.commit()

    resp = client.get("/similarity-hints")
    assert resp.status_code == 200
    assert "ASUS RTX 5070 PRIME 12G" in resp.text
    assert "85%" in resp.text


def test_similarity_hints_refresh_creates_new_hints():
    client, Session_ = _make_client()
    t = datetime.datetime(2026, 2, 1)
    with Session_() as session:
        cat = Category(name="顯示卡VGA")
        sub = Subcategory(name="NVIDIA", category=cat)
        session.add_all([cat, sub])
        session.flush()
        a = Product(category_id=cat.id, subcategory_id=sub.id, current_name="ASUS RTX 5070 PRIME 12G",
                   current_price=100, is_active=False, first_seen_at=t, last_seen_at=t, created_at=t)
        b = Product(category_id=cat.id, subcategory_id=sub.id, current_name="ASUS RTX 5070 PRIME OC 12GB",
                   current_price=200, is_active=True, first_seen_at=t, last_seen_at=t, created_at=t)
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
                   current_price=100, is_active=True, first_seen_at=t, last_seen_at=t, created_at=t)
        b = Product(category_id=cat.id, subcategory_id=sub.id, current_name="商品B獨特字串",
                   current_price=200, is_active=True, first_seen_at=t, last_seen_at=t, created_at=t)
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
                   current_price=100, is_active=False, first_seen_at=t, last_seen_at=t, created_at=t)
        b = Product(category_id=cat.id, subcategory_id=sub.id, current_name="新名稱在售商品",
                   current_price=200, is_active=True, first_seen_at=t, last_seen_at=t, created_at=t)
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
                   current_price=100, is_active=True, first_seen_at=t, last_seen_at=t, created_at=t)
        b = Product(category_id=cat.id, subcategory_id=sub.id, current_name="商品B獨特字串批量忽略",
                   current_price=200, is_active=True, first_seen_at=t, last_seen_at=t, created_at=t)
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


def test_similarity_hints_page_has_checkbox_and_no_per_row_action_column():
    client, Session_ = _make_client()
    t = datetime.datetime(2026, 2, 1)
    with Session_() as session:
        cat = Category(name="顯示卡VGA")
        sub = Subcategory(name="NVIDIA", category=cat)
        session.add_all([cat, sub])
        session.flush()
        a = Product(category_id=cat.id, subcategory_id=sub.id, current_name="核取方塊測試A",
                   current_price=100, is_active=True, first_seen_at=t, last_seen_at=t, created_at=t)
        b = Product(category_id=cat.id, subcategory_id=sub.id, current_name="核取方塊測試B",
                   current_price=200, is_active=True, first_seen_at=t, last_seen_at=t, created_at=t)
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
    assert "批量合併" in resp.text
    assert "批量忽略" in resp.text
    # 舊版每列一個「不是同一商品，忽略」的獨立表單已移除
    assert "不是同一商品，忽略" not in resp.text
