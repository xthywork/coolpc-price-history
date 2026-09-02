import datetime
import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session
from coolpc.db.models import Base, Category, Subcategory, Product, ProductName, PriceHistory
from coolpc.merging.service import merge_products, undo_merge, MergeError

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
                      is_active=False, first_seen_at=t, last_seen_at=t, created_at=t)
    target = Product(category_id=cat.id, subcategory_id=sub.id,
                      current_name="ASUS RTX 5070 PRIME OC 12GB", current_price=19990,
                      is_active=True, first_seen_at=t, last_seen_at=t, created_at=t)
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
                     first_seen_at=t, last_seen_at=t, created_at=t)
    session.add(third)
    session.commit()

    with pytest.raises(MergeError):
        merge_products(session, third.id, source.id)  # source 已被合併，不可再當 target

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
