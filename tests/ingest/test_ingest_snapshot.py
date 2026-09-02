import datetime
from sqlalchemy import create_engine
from sqlalchemy.orm import Session
from coolpc.db.models import Base, Product
from coolpc.ingest.service import ingest_snapshot
from coolpc.parser.models import ParsedProduct, ParsedSnapshot

def _session():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    return Session(engine)

def _snap(fetched_at, products):
    return ParsedSnapshot(fetched_at=fetched_at, products=products)

def test_ingest_snapshot_counts_new_products():
    session = _session()
    t0 = datetime.datetime(2026, 2, 1)
    parsed = _snap(t0, [
        ParsedProduct("顯示卡VGA", "NVIDIA", "ASUS DUAL-RTX3050-O6G", 7990, None, "◆ ★"),
        ParsedProduct("顯示卡VGA", "NVIDIA", "微星 RTX3050 VENTUS 2X E 6G OC", 7990, None, "◆ ★"),
    ])
    snap = ingest_snapshot(session, parsed, scrape_type="manual", raw_html_path="/x.html")
    session.commit()

    assert snap.total_products == 2
    assert snap.new_products == 2
    assert snap.delisted_products == 0
    assert snap.status == "success"
    assert session.query(Product).count() == 2

def test_ingest_snapshot_detects_price_change_and_delisting():
    session = _session()
    t0 = datetime.datetime(2026, 2, 1)
    t1 = datetime.datetime(2026, 2, 1, 6, 0)

    snap1 = ingest_snapshot(session, _snap(t0, [
        ParsedProduct("顯示卡VGA", "NVIDIA", "ASUS DUAL-RTX3050-O6G", 7990, None, "◆ ★"),
        ParsedProduct("顯示卡VGA", "NVIDIA", "微星 RTX3050 VENTUS 2X E 6G OC", 7990, None, "◆ ★"),
    ]), scrape_type="manual", raw_html_path=None)
    session.commit()
    assert snap1.new_products == 2

    # 第二次抓取：第一個商品漲價，第二個商品消失（應標記下架）
    snap2 = ingest_snapshot(session, _snap(t1, [
        ParsedProduct("顯示卡VGA", "NVIDIA", "ASUS DUAL-RTX3050-O6G", 8490, None, "◆ ★ 熱賣"),
    ]), scrape_type="scheduled", raw_html_path=None)
    session.commit()

    assert snap2.new_products == 0
    assert snap2.price_up_count == 1
    assert snap2.price_down_count == 0
    assert snap2.delisted_products == 1

    active = session.query(Product).filter_by(is_active=True).all()
    inactive = session.query(Product).filter_by(is_active=False).all()
    assert len(active) == 1
    assert active[0].current_name == "ASUS DUAL-RTX3050-O6G"
    assert len(inactive) == 1
    assert inactive[0].current_name == "微星 RTX3050 VENTUS 2X E 6G OC"

def test_ingest_snapshot_reactivates_delisted_product():
    session = _session()
    t0 = datetime.datetime(2026, 2, 1)
    t1 = datetime.datetime(2026, 2, 1, 6, 0)
    t2 = datetime.datetime(2026, 2, 1, 12, 0)

    ingest_snapshot(session, _snap(t0, [
        ParsedProduct("顯示卡VGA", "NVIDIA", "微星 RTX3050 VENTUS 2X E 6G OC", 7990, None, "◆ ★"),
    ]), scrape_type="manual", raw_html_path=None)
    session.commit()

    ingest_snapshot(session, _snap(t1, []), scrape_type="scheduled", raw_html_path=None)
    session.commit()
    delisted = session.query(Product).filter_by(is_active=False).one()
    assert delisted.current_name == "微星 RTX3050 VENTUS 2X E 6G OC"

    ingest_snapshot(session, _snap(t2, [
        ParsedProduct("顯示卡VGA", "NVIDIA", "微星 RTX3050 VENTUS 2X E 6G OC", 7990, None, "◆ ★"),
    ]), scrape_type="scheduled", raw_html_path=None)
    session.commit()
    reactivated = session.query(Product).one()
    assert reactivated.is_active is True
    assert reactivated.last_seen_at == t2
