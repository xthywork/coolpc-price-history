"""端對端整合測試：scrape -> 商品改名 -> admin 合併兩個商品 -> 舊名稱仍可搜尋
-> 價格歷史合併呈現 -> undo -> 兩個商品完全復原。

這是規格書裡描述的核心使用情境，但先前只有各模組各自的單元測試片段覆蓋
到（ingest 一份、merge 一份、stats 一份、search 一份），從沒有單一測試在
「同一份資料」上，讓 merge_products/undo_merge 這兩個真正的 service 函式
和 search_products、compute_product_stats 一起跑過一輪。C1（合併鏈遺漏
歷史）、C2（out-of-order undo 破壞名稱歸屬）這兩個 Critical bug 都正是活
在這個模組間的縫隙裡才沒被抓到，所以這裡刻意全部呼叫真正的 service
函式，不手動操作 DB。"""
import datetime
from sqlalchemy import create_engine
from sqlalchemy.orm import Session
from coolpc.db.models import Base, ProductName, PriceHistory
from coolpc.ingest.service import ingest_snapshot
from coolpc.merging.service import merge_products, undo_merge
from coolpc.search.service import SearchFilters, search_products
from coolpc.stats.service import compute_product_stats
from coolpc.parser.models import ParsedProduct, ParsedSnapshot


def _session():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    return Session(engine)


OLD_NAME = "ASUS RTX 5070 PRIME 12G"
NEW_NAME = "ASUS RTX 5070 PRIME OC 12GB"


def test_full_merge_undo_journey_with_real_service_functions():
    session = _session()
    t0 = datetime.datetime(2026, 2, 1)
    t1 = datetime.datetime(2026, 3, 1)

    # 1. 第一次抓取：商品以舊名稱、價格 18990 上架
    snap1 = ingest_snapshot(
        session,
        ParsedSnapshot(fetched_at=t0, products=[
            ParsedProduct("顯示卡VGA", "NVIDIA", OLD_NAME, 18990, None, "◆ ★"),
        ]),
        scrape_type="manual", raw_html_path=None,
    )
    session.commit()
    assert snap1.new_products == 1

    old_product_id = session.query(ProductName).filter_by(name=OLD_NAME).one().product_id

    # 2. 第二次抓取（不同 fetched_at）：同一顆實體商品現在改用新名稱上架，
    #    價格變成 19990。依照系統精確比對名稱的規則，這會被當成「全新商品」
    #    ——這是設計上的預期行為（不是 bug），才需要 admin 手動合併。
    snap2 = ingest_snapshot(
        session,
        ParsedSnapshot(fetched_at=t1, products=[
            ParsedProduct("顯示卡VGA", "NVIDIA", NEW_NAME, 19990, None, "◆ ★"),
        ]),
        scrape_type="scheduled", raw_html_path=None,
    )
    session.commit()
    assert snap2.new_products == 1

    new_product_id = session.query(ProductName).filter_by(name=NEW_NAME).one().product_id
    assert new_product_id != old_product_id

    total_price_history_before_merge = session.query(PriceHistory).count()
    assert total_price_history_before_merge == 2

    # 3. admin 呼叫真正的 merge_products，把舊名稱商品併入新名稱商品
    merge_log = merge_products(session, source_id=old_product_id, target_id=new_product_id)
    session.commit()

    # 4a. compute_product_stats(target) 應同時反映兩邊的價格歷史
    #     （18990 是最低價、19990 是最高價，橫跨兩次快照）
    stats = compute_product_stats(session, new_product_id)
    assert stats.all_time_low == 18990
    assert stats.all_time_high == 19990

    # 4b. 用舊名稱搜尋，仍要能找到合併後的商品（target），而不是被排除的 source
    products, total = search_products(session, SearchFilters(q=OLD_NAME))
    assert total == 1
    assert products[0].id == new_product_id

    # source 本身已經合併掉，不該再出現在任何搜尋結果裡
    products_by_new_name, _ = search_products(session, SearchFilters(q=NEW_NAME))
    assert {p.id for p in products_by_new_name} == {new_product_id}

    # 全程沒有任何一筆價格歷史被搬動或刪除，只是查詢視角改變
    assert session.query(PriceHistory).count() == total_price_history_before_merge

    # 5. admin 後悔了，呼叫真正的 undo_merge
    undo_merge(session, merge_log.id)
    session.commit()

    # 6. 兩個商品應該完全恢復成合併前各自獨立的狀態
    old_stats = compute_product_stats(session, old_product_id)
    new_stats = compute_product_stats(session, new_product_id)
    assert old_stats.all_time_low == old_stats.all_time_high == 18990
    assert new_stats.all_time_low == new_stats.all_time_high == 19990

    old_hits, _ = search_products(session, SearchFilters(q=OLD_NAME))
    new_hits, _ = search_products(session, SearchFilters(q=NEW_NAME))
    assert {p.id for p in old_hits} == {old_product_id}
    assert {p.id for p in new_hits} == {new_product_id}

    # 沒有任何一筆價格歷史在合併/undo 的過程中遺失
    assert session.query(PriceHistory).count() == total_price_history_before_merge
    assert session.query(PriceHistory).filter_by(product_id=old_product_id).count() == 1
    assert session.query(PriceHistory).filter_by(product_id=new_product_id).count() == 1
