import datetime
import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session
from coolpc.db.models import Base, Category, Subcategory, Product, ProductName, PriceHistory, MergeLog
from coolpc.merging.service import merge_products, merge_products_batch, undo_merge, MergeError

def _session():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    return Session(engine)

def _setup_two_products(session):
    t = datetime.datetime(2026, 2, 1)
    cat = Category(name="顯示卡VGA")
    sub = Subcategory(name="NVIDIA", category=cat)
    session.add_all([cat, sub])
    session.flush()

    source = Product(category_id=cat.id, subcategory_id=sub.id,
                      current_name="ASUS RTX 5070 PRIME 12G", current_price=18990,
                      is_active=False, last_seen_at=t, created_at=t)
    target = Product(category_id=cat.id, subcategory_id=sub.id,
                      current_name="ASUS RTX 5070 PRIME OC 12GB", current_price=19990,
                      is_active=True, last_seen_at=t, created_at=t)
    session.add_all([source, target])
    session.flush()
    session.add_all([
        ProductName(product_id=source.id, name="ASUS RTX 5070 PRIME 12G", first_seen_at=t, last_seen_at=t),
        ProductName(product_id=target.id, name="ASUS RTX 5070 PRIME OC 12GB", first_seen_at=t, last_seen_at=t),
    ])
    session.add_all([
        PriceHistory(product_id=source.id, price=18990, status=None, badges="", scraped_at=t, snapshot_id=1),
        PriceHistory(product_id=target.id, price=19990, status=None, badges="", scraped_at=t, snapshot_id=1),
    ])
    session.commit()
    return source, target

def test_merge_reassigns_names_and_marks_source():
    session = _session()
    source, target = _setup_two_products(session)

    merge_log = merge_products(session, source.id, target.id)
    session.commit()

    session.refresh(source)
    assert source.merged_into_id == target.id

    names = session.query(ProductName).all()
    assert all(n.product_id == target.id for n in names)
    assert {n.name for n in names} == {"ASUS RTX 5070 PRIME 12G", "ASUS RTX 5070 PRIME OC 12GB"}

    # 舊名稱搜尋仍要能找到合併後商品
    hit = session.query(ProductName).filter_by(name="ASUS RTX 5070 PRIME 12G").one()
    assert hit.product_id == target.id

    # 歷史價格完全沒被搬動或刪除
    assert session.query(PriceHistory).filter_by(product_id=source.id).count() == 1
    assert session.query(PriceHistory).filter_by(product_id=target.id).count() == 1

def test_merge_same_id_raises():
    session = _session()
    source, target = _setup_two_products(session)
    with pytest.raises(MergeError):
        merge_products(session, source.id, source.id)

def test_merge_into_already_merged_target_raises():
    session = _session()
    source, target = _setup_two_products(session)
    merge_products(session, source.id, target.id)
    session.commit()

    t = datetime.datetime(2026, 2, 2)
    third = Product(category_id=target.category_id, subcategory_id=target.subcategory_id,
                     current_name="第三個商品", current_price=100, is_active=True,
                     last_seen_at=t, created_at=t)
    session.add(third)
    session.commit()

    with pytest.raises(MergeError):
        merge_products(session, third.id, source.id)  # source 已被合併，不可再當 target


def test_batch_merge_merges_multiple_sources_into_specified_target():
    session = _session()
    source_a, target = _setup_two_products(session)
    t = datetime.datetime(2026, 2, 2)
    source_b = Product(
        category_id=target.category_id,
        subcategory_id=target.subcategory_id,
        current_name="第三個商品",
        current_price=100,
        is_active=False,
        last_seen_at=t,
        created_at=t,
    )
    session.add(source_b)
    session.flush()
    session.add(ProductName(
        product_id=source_b.id,
        name="第三個商品",
        first_seen_at=t,
        last_seen_at=t,
    ))
    session.commit()

    logs = merge_products_batch(session, [source_a.id, source_b.id], target.id, now=t)

    assert len(logs) == 2
    assert source_a.merged_into_id == target.id
    assert source_b.merged_into_id == target.id
    assert [log.target_product_id for log in logs] == [target.id, target.id]
    assert {log.source_product_id for log in logs} == {source_a.id, source_b.id}


def test_batch_merge_prevalidates_all_sources_before_caller_rollback():
    session = _session()
    source_a, target = _setup_two_products(session)
    t = datetime.datetime(2026, 2, 2)
    merged_source = Product(
        category_id=target.category_id,
        subcategory_id=target.subcategory_id,
        current_name="已合併商品",
        current_price=100,
        is_active=False,
        last_seen_at=t,
        created_at=t,
        merged_into_id=target.id,
    )
    session.add(merged_source)
    session.flush()
    session.add(ProductName(
        product_id=merged_source.id,
        name="已合併商品",
        first_seen_at=t,
        last_seen_at=t,
    ))
    session.commit()

    with pytest.raises(MergeError):
        merge_products_batch(session, [source_a.id, merged_source.id], target.id, now=t)

    assert source_a.merged_into_id is None
    assert session.query(MergeLog).count() == 0
    session.rollback()

    assert source_a.merged_into_id is None
    assert session.query(MergeLog).count() == 0

def test_undo_merge_restores_original_state():
    session = _session()
    source, target = _setup_two_products(session)
    merge_log = merge_products(session, source.id, target.id)
    session.commit()

    undo_merge(session, merge_log.id)
    session.commit()

    session.refresh(source)
    assert source.merged_into_id is None

    source_name = session.query(ProductName).filter_by(name="ASUS RTX 5070 PRIME 12G").one()
    target_name = session.query(ProductName).filter_by(name="ASUS RTX 5070 PRIME OC 12GB").one()
    assert source_name.product_id == source.id
    assert target_name.product_id == target.id

    assert session.query(PriceHistory).filter_by(product_id=source.id).count() == 1
    assert session.query(PriceHistory).filter_by(product_id=target.id).count() == 1

def test_undo_already_undone_raises():
    session = _session()
    source, target = _setup_two_products(session)
    merge_log = merge_products(session, source.id, target.id)
    session.commit()
    undo_merge(session, merge_log.id)
    session.commit()
    with pytest.raises(MergeError):
        undo_merge(session, merge_log.id)

def test_undo_with_multiple_names_only_restores_moved_ones():
    """target 原本就有自己的名稱，undo 後不能誤把 target 自己的名稱也搬走。"""
    session = _session()
    source, target = _setup_two_products(session)
    t = datetime.datetime(2026, 2, 3)
    # target 之後又多了一個新曾用名（模擬合併後 target 自己又改名一次）
    session.add(ProductName(product_id=target.id, name="ASUS RTX 5070 PRIME OC 12GB V2",
                             first_seen_at=t, last_seen_at=t))
    session.commit()

    merge_log = merge_products(session, source.id, target.id)
    session.commit()
    undo_merge(session, merge_log.id)
    session.commit()

    assert session.query(ProductName).filter_by(name="ASUS RTX 5070 PRIME OC 12GB V2").one().product_id == target.id
    assert session.query(ProductName).filter_by(name="ASUS RTX 5070 PRIME 12G").one().product_id == source.id

def test_undo_out_of_order_in_merge_chain_is_rejected_then_succeeds_in_order():
    """A 併入 B，之後 B 又併入 C（都是透過真正的 merge_products 呼叫）。
    若在 B->C 仍然生效時就想先 Undo A->B，這個 Undo 必須被拒絕，
    因為 A 的名稱早已經(隨著 B->C 合併)被搬到 C 身上，A->B 當時記錄的
    moved_name_ids 已經不是「目前掛在 B 上」的狀態了。
    必須先 Undo 較新的 B->C，再 Undo A->B，兩者才會依序成功。"""
    session = _session()
    t = datetime.datetime(2026, 2, 1)
    cat = Category(name="顯示卡VGA")
    sub = Subcategory(name="NVIDIA", category=cat)
    session.add_all([cat, sub])
    session.flush()

    a = Product(category_id=cat.id, subcategory_id=sub.id, current_name="A商品",
                current_price=1000, is_active=False, last_seen_at=t, created_at=t)
    b = Product(category_id=cat.id, subcategory_id=sub.id, current_name="B商品",
                current_price=2000, is_active=False, last_seen_at=t, created_at=t)
    c = Product(category_id=cat.id, subcategory_id=sub.id, current_name="C商品",
                current_price=3000, is_active=True, last_seen_at=t, created_at=t)
    session.add_all([a, b, c])
    session.flush()
    session.add_all([
        ProductName(product_id=a.id, name="A的名稱", first_seen_at=t, last_seen_at=t),
        ProductName(product_id=b.id, name="B的名稱", first_seen_at=t, last_seen_at=t),
        ProductName(product_id=c.id, name="C的名稱", first_seen_at=t, last_seen_at=t),
    ])
    session.add_all([
        PriceHistory(product_id=a.id, price=1000, status=None, badges="", scraped_at=t, snapshot_id=1),
        PriceHistory(product_id=b.id, price=2000, status=None, badges="", scraped_at=t, snapshot_id=1),
        PriceHistory(product_id=c.id, price=3000, status=None, badges="", scraped_at=t, snapshot_id=1),
    ])
    session.commit()

    merge_ab = merge_products(session, a.id, b.id)
    session.commit()
    merge_bc = merge_products(session, b.id, c.id)
    session.commit()

    # 此時 A 的名稱、B 的名稱都已經掛在 C 身上
    assert {n.product_id for n in session.query(ProductName).all()} == {c.id}

    # 先 Undo 較舊的 A->B：必須被拒絕，因為 A 的名稱已經不在 B 身上了（在 C 身上）
    with pytest.raises(MergeError):
        undo_merge(session, merge_ab.id)
    session.rollback()

    # 改成先 Undo 較新的 B->C：應該成功，因為 B->C 記錄搬動的名稱目前確實都還在 C 身上
    undo_merge(session, merge_bc.id)
    session.commit()

    session.refresh(b)
    assert b.merged_into_id is None
    # B 自己的名稱、以及 A 的名稱（A->B 尚未 Undo，所以仍掛在 B 上）都應回到 B
    names_by_product = {n.name: n.product_id for n in session.query(ProductName).all()}
    assert names_by_product["B的名稱"] == b.id
    assert names_by_product["A的名稱"] == b.id
    assert names_by_product["C的名稱"] == c.id

    # 最後 Undo 較舊的 A->B：現在 B 是目前正確、未被搬動過的擁有者，應該成功
    undo_merge(session, merge_ab.id)
    session.commit()

    session.refresh(a)
    assert a.merged_into_id is None
    names_by_product = {n.name: n.product_id for n in session.query(ProductName).all()}
    assert names_by_product["A的名稱"] == a.id
    assert names_by_product["B的名稱"] == b.id
    assert names_by_product["C的名稱"] == c.id

    # 全程沒有任何價格歷史遺失
    assert session.query(PriceHistory).filter_by(product_id=a.id).count() == 1
    assert session.query(PriceHistory).filter_by(product_id=b.id).count() == 1
    assert session.query(PriceHistory).filter_by(product_id=c.id).count() == 1
