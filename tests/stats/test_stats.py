import datetime
from sqlalchemy import create_engine
from sqlalchemy.orm import Session
from coolpc.db.models import Base, Category, Subcategory, Product, PriceHistory
from coolpc.stats.service import compute_product_stats, get_price_history, get_merged_group_product_ids

def _session():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    return Session(engine)

def _make_product(session, cat, sub, name, price, t):
    p = Product(category_id=cat.id, subcategory_id=sub.id, current_name=name,
                current_price=price, is_active=True,
                last_seen_at=t, created_at=t)
    session.add(p)
    session.flush()
    return p

def test_compute_product_stats_change_and_ranges():
    session = _session()
    cat = Category(name="C")
    sub = Subcategory(name="S", category=cat)
    session.add_all([cat, sub])
    session.flush()
    now = datetime.datetime(2026, 2, 10)
    p = _make_product(session, cat, sub, "商品A", 9000, now)

    prices = [
        (now - datetime.timedelta(days=95), 10000),
        (now - datetime.timedelta(days=40), 8000),
        (now - datetime.timedelta(days=10), 9500),
        (now - datetime.timedelta(days=1), 8500),
        (now, 9000),
    ]
    for i, (t, price) in enumerate(prices):
        session.add(PriceHistory(product_id=p.id, price=price, status=None, badges="",
                                  scraped_at=t, snapshot_id=i))
    session.commit()

    stats = compute_product_stats(session, p.id, now=now)
    assert stats.current_price == 9000
    assert stats.previous_price == 8500
    assert stats.change_amount == 500
    assert round(stats.change_percent, 2) == round(500 / 8500 * 100, 2)
    assert (stats.low_7d, stats.high_7d) == (8500, 9000)
    assert (stats.low_30d, stats.high_30d) == (8500, 9500)
    assert (stats.low_90d, stats.high_90d) == (8000, 9500)
    assert stats.all_time_low == 8000
    assert stats.all_time_high == 10000

def test_compute_product_stats_first_seen_has_no_previous_price():
    session = _session()
    cat = Category(name="C")
    sub = Subcategory(name="S", category=cat)
    session.add_all([cat, sub])
    session.flush()
    now = datetime.datetime(2026, 2, 10)
    p = _make_product(session, cat, sub, "商品B", 5000, now)
    session.add(PriceHistory(product_id=p.id, price=5000, status=None, badges="",
                              scraped_at=now, snapshot_id=1))
    session.commit()

    stats = compute_product_stats(session, p.id, now=now)
    assert stats.previous_price is None
    assert stats.change_amount is None
    assert stats.all_time_low == 5000
    assert stats.all_time_high == 5000

def test_compute_product_stats_includes_merged_source_history():
    session = _session()
    cat = Category(name="C")
    sub = Subcategory(name="S", category=cat)
    session.add_all([cat, sub])
    session.flush()
    now = datetime.datetime(2026, 2, 10)
    source = _make_product(session, cat, sub, "舊名", 7000, now - datetime.timedelta(days=5))
    target = _make_product(session, cat, sub, "新名", 9000, now)
    session.add(PriceHistory(product_id=source.id, price=7000, status=None, badges="",
                              scraped_at=now - datetime.timedelta(days=5), snapshot_id=1))
    session.add(PriceHistory(product_id=target.id, price=9000, status=None, badges="",
                              scraped_at=now, snapshot_id=2))
    session.commit()
    source.merged_into_id = target.id
    session.commit()

    stats = compute_product_stats(session, target.id, now=now)
    assert stats.all_time_low == 7000
    assert stats.all_time_high == 9000

    history = get_price_history(session, target.id)
    assert len(history) == 2
    assert {h.product_id for h in history} == {source.id, target.id}

def test_compute_product_stats_includes_transitive_merge_chain():
    """A 併入 B，之後 B 又併入 C（兩次合併發生當下都合法：A->B 發生時
    B.merged_into_id 還是 None；B->C 發生時是另一次獨立事件）。
    從 C 查詢時，A 的價格歷史也必須被納入，不能因為只展開一層而遺漏。"""
    session = _session()
    cat = Category(name="C")
    sub = Subcategory(name="S", category=cat)
    session.add_all([cat, sub])
    session.flush()
    now = datetime.datetime(2026, 2, 10)
    a = _make_product(session, cat, sub, "商品A舊名", 9000, now - datetime.timedelta(days=20))
    b = _make_product(session, cat, sub, "商品B曾用名", 9500, now - datetime.timedelta(days=10))
    c = _make_product(session, cat, sub, "商品C現名", 9200, now)

    # A 的歷史價格刻意設成極端值，證明它確實被納入計算，而不只是出現在 id 清單裡
    session.add(PriceHistory(product_id=a.id, price=1, status=None, badges="",
                              scraped_at=now - datetime.timedelta(days=20), snapshot_id=1))
    session.add(PriceHistory(product_id=b.id, price=9500, status=None, badges="",
                              scraped_at=now - datetime.timedelta(days=10), snapshot_id=2))
    session.add(PriceHistory(product_id=c.id, price=99999, status=None, badges="",
                              scraped_at=now, snapshot_id=3))
    session.commit()

    # A 先併入 B，之後 B 再併入 C（模擬先後兩次獨立、各自合法的合併事件）
    a.merged_into_id = b.id
    session.commit()
    b.merged_into_id = c.id
    session.commit()

    group = get_merged_group_product_ids(session, c.id)
    assert set(group) == {a.id, b.id, c.id}

    stats = compute_product_stats(session, c.id, now=now)
    assert stats.all_time_low == 1
    assert stats.all_time_high == 99999
