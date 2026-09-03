import datetime
from sqlalchemy import create_engine
from sqlalchemy.orm import Session
from coolpc.db.models import Base, Product, ScrapeSnapshot, PriceHistory
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
    # I6 修正後，下架比對只在「本次商品數不低於前一次成功快照的 70%」時才會
    # 真正執行，所以這裡故意準備 4 個基準商品，第二次只少 1 個（75% >= 70%），
    # 確保這是一次「正常範圍內的下架」而不會被誤判為 partial。
    session = _session()
    t0 = datetime.datetime(2026, 2, 1)
    t1 = datetime.datetime(2026, 2, 1, 6, 0)

    snap1 = ingest_snapshot(session, _snap(t0, [
        ParsedProduct("顯示卡VGA", "NVIDIA", "ASUS DUAL-RTX3050-O6G", 7990, None, "◆ ★"),
        ParsedProduct("顯示卡VGA", "NVIDIA", "微星 RTX3050 VENTUS 2X E 6G OC", 7990, None, "◆ ★"),
        ParsedProduct("顯示卡VGA", "NVIDIA", "技嘉 RTX3050 EAGLE 6G", 7990, None, "◆ ★"),
        ParsedProduct("顯示卡VGA", "NVIDIA", "華碩 RTX3050 DUAL OC 6G", 7990, None, "◆ ★"),
    ]), scrape_type="manual", raw_html_path=None)
    session.commit()
    assert snap1.new_products == 4
    assert snap1.status == "success"

    # 第二次抓取：第一個商品漲價，第二個商品消失（應標記下架），其餘兩個維持不變
    snap2 = ingest_snapshot(session, _snap(t1, [
        ParsedProduct("顯示卡VGA", "NVIDIA", "ASUS DUAL-RTX3050-O6G", 8490, None, "◆ ★ 熱賣"),
        ParsedProduct("顯示卡VGA", "NVIDIA", "技嘉 RTX3050 EAGLE 6G", 7990, None, "◆ ★"),
        ParsedProduct("顯示卡VGA", "NVIDIA", "華碩 RTX3050 DUAL OC 6G", 7990, None, "◆ ★"),
    ]), scrape_type="scheduled", raw_html_path=None)
    session.commit()

    assert snap2.status == "success"
    assert snap2.new_products == 0
    assert snap2.price_up_count == 1
    assert snap2.price_down_count == 0
    assert snap2.delisted_products == 1

    active = session.query(Product).filter_by(is_active=True).all()
    inactive = session.query(Product).filter_by(is_active=False).all()
    assert len(active) == 3
    assert len(inactive) == 1
    assert inactive[0].current_name == "微星 RTX3050 VENTUS 2X E 6G OC"

def test_ingest_snapshot_reactivates_delisted_product():
    # 同樣為了不誤觸 I6 的 partial 保護，準備 4 個基準商品，第二次只少目標
    # 商品一個（75% >= 70%），確保下架是「真的下架」而不是被跳過。
    session = _session()
    t0 = datetime.datetime(2026, 2, 1)
    t1 = datetime.datetime(2026, 2, 1, 6, 0)
    t2 = datetime.datetime(2026, 2, 1, 12, 0)

    ingest_snapshot(session, _snap(t0, [
        ParsedProduct("顯示卡VGA", "NVIDIA", "微星 RTX3050 VENTUS 2X E 6G OC", 7990, None, "◆ ★"),
        ParsedProduct("顯示卡VGA", "NVIDIA", "技嘉 RTX3050 EAGLE 6G", 7990, None, "◆ ★"),
        ParsedProduct("顯示卡VGA", "NVIDIA", "華碩 RTX3050 DUAL OC 6G", 7990, None, "◆ ★"),
        ParsedProduct("顯示卡VGA", "NVIDIA", "index 填充商品", 100, None, "◆"),
    ]), scrape_type="manual", raw_html_path=None)
    session.commit()

    snap2 = ingest_snapshot(session, _snap(t1, [
        ParsedProduct("顯示卡VGA", "NVIDIA", "技嘉 RTX3050 EAGLE 6G", 7990, None, "◆ ★"),
        ParsedProduct("顯示卡VGA", "NVIDIA", "華碩 RTX3050 DUAL OC 6G", 7990, None, "◆ ★"),
        ParsedProduct("顯示卡VGA", "NVIDIA", "index 填充商品", 100, None, "◆"),
    ]), scrape_type="scheduled", raw_html_path=None)
    session.commit()
    assert snap2.status == "success"
    delisted = session.query(Product).filter_by(is_active=False).one()
    assert delisted.current_name == "微星 RTX3050 VENTUS 2X E 6G OC"

    ingest_snapshot(session, _snap(t2, [
        ParsedProduct("顯示卡VGA", "NVIDIA", "微星 RTX3050 VENTUS 2X E 6G OC", 7990, None, "◆ ★"),
        ParsedProduct("顯示卡VGA", "NVIDIA", "技嘉 RTX3050 EAGLE 6G", 7990, None, "◆ ★"),
        ParsedProduct("顯示卡VGA", "NVIDIA", "華碩 RTX3050 DUAL OC 6G", 7990, None, "◆ ★"),
        ParsedProduct("顯示卡VGA", "NVIDIA", "index 填充商品", 100, None, "◆"),
    ]), scrape_type="scheduled", raw_html_path=None)
    session.commit()
    reactivated = session.query(Product).filter_by(current_name="微星 RTX3050 VENTUS 2X E 6G OC").one()
    assert reactivated.is_active is True
    assert reactivated.last_seen_at == t2

def test_ingest_snapshot_reimport_same_fetched_at_is_idempotent():
    """C3: 重複匯入 fetched_at 完全相同的快照，不應該重複建立 ScrapeSnapshot
    或 PriceHistory（避免補匯流程重疊日期範圍時，價格歷史被灌兩倍）。"""
    session = _session()
    t0 = datetime.datetime(2026, 2, 1)
    products = [
        ParsedProduct("顯示卡VGA", "NVIDIA", "ASUS DUAL-RTX3050-O6G", 7990, None, "◆ ★"),
        ParsedProduct("顯示卡VGA", "NVIDIA", "微星 RTX3050 VENTUS 2X E 6G OC", 7990, None, "◆ ★"),
    ]

    snap1 = ingest_snapshot(session, _snap(t0, products), scrape_type="import", raw_html_path="/a.html")
    session.commit()
    first_id = snap1.id
    assert session.query(ScrapeSnapshot).count() == 1
    product_ids = [p.id for p in session.query(Product).order_by(Product.id).all()]
    assert session.query(PriceHistory).count() == 2

    # 完全相同的內容（同一個 fetched_at、同樣的商品）再匯入一次
    snap2 = ingest_snapshot(session, _snap(t0, products), scrape_type="import", raw_html_path="/a.html")
    session.commit()

    assert snap2.id == first_id
    assert session.query(ScrapeSnapshot).count() == 1
    assert session.query(PriceHistory).count() == 2
    for pid in product_ids:
        assert session.query(PriceHistory).filter_by(product_id=pid).count() == 1

def test_ingest_snapshot_marks_partial_and_skips_delisting_on_sharp_drop():
    """I6: 若本次快照商品數遠低於前一次成功快照（低於 70%），視為疑似解析
    不完整，標記為 partial 並完全跳過下架比對，避免大量商品被誤下架。"""
    session = _session()
    t0 = datetime.datetime(2026, 2, 1)
    t1 = datetime.datetime(2026, 2, 1, 6, 0)

    snap1 = ingest_snapshot(session, _snap(t0, [
        ParsedProduct("顯示卡VGA", "NVIDIA", f"商品{i}", 1000 + i, None, "◆")
        for i in range(10)
    ]), scrape_type="manual", raw_html_path=None)
    session.commit()
    assert snap1.status == "success"
    assert snap1.total_products == 10

    # 第二次快照只解析到 2 個商品（遠低於 10 個的 70%）
    snap2 = ingest_snapshot(session, _snap(t1, [
        ParsedProduct("顯示卡VGA", "NVIDIA", "商品0", 1000, None, "◆"),
        ParsedProduct("顯示卡VGA", "NVIDIA", "商品1", 1001, None, "◆"),
    ]), scrape_type="scheduled", raw_html_path=None)
    session.commit()

    assert snap2.status == "partial"
    assert snap2.delisted_products == 0
    # 原本 10 個商品全部仍應維持 is_active=True，即使有 8 個沒出現在這次快照
    assert session.query(Product).filter_by(is_active=True).count() == 10
