import glob
import os
import subprocess
import sys
from sqlalchemy import create_engine, text, func
from sqlalchemy.orm import Session
from coolpc.db.models import Product, ProductName, PriceHistory, Category
from coolpc.parser.html_parser import parse_html
from coolpc.ingest.service import ingest_snapshot

SAMPLE_DIR = "/home/xthybot/coolpc/download"


def _session(tmp_path):
    db_path = tmp_path / "regression.db"
    env = os.environ.copy()
    env["COOLPC_DB_PATH"] = str(db_path)
    subprocess.run([sys.executable, "-m", "alembic", "upgrade", "head"], check=True, env=env)
    engine = create_engine(f"sqlite:///{db_path}")
    return Session(engine)


def test_import_real_chronological_sequence_without_errors_or_data_loss(tmp_path):
    files = sorted(glob.glob(f"{SAMPLE_DIR}/*.html"))[:40]
    assert len(files) == 40

    session = _session(tmp_path)
    snapshots = []
    for path in files:
        with open(path, "rb") as f:
            parsed = parse_html(f.read())  # 全部必須成功解析，不拋例外
        snap = ingest_snapshot(session, parsed, scrape_type="import", raw_html_path=path)
        session.commit()
        snapshots.append(snap)

    assert all(s.status == "success" for s in snapshots)

    # 中文無亂碼：已知分類名稱必須正確出現
    category_names = {c.name for c in session.query(Category).all()}
    assert "顯示卡VGA" in category_names
    assert "處理器 CPU" in category_names

    # 比對邏輯正確運作：總商品數不應隨快照數量線性暴增
    # （若比對失效、每次都誤判成新商品，數量會遠超單一快照商品數的合理倍數）
    total_products = session.query(Product).count()
    assert total_products < snapshots[-1].total_products * 3

    # 價格歷史正確累積：應有商品累積超過一筆價格紀錄
    counts = (
        session.query(PriceHistory.product_id, func.count(PriceHistory.id))
        .group_by(PriceHistory.product_id).all()
    )
    assert any(count > 1 for _, count in counts)

    # 舊名稱不會消失
    assert session.query(ProductName).count() >= total_products

    # FTS5 觸發器在真實批次匯入規模下仍正確同步（不只是 Task 4 的小規模單元測試）。
    # Task 4 的觸發器把每個名稱索引成「整串原文 + 每個重疊 2-gram」多筆記錄，
    # 不是 1:1，所以這裡驗證「每個名稱至少有對應記錄」而非精確筆數相等。
    fts_count = session.execute(text("SELECT COUNT(*) FROM products_fts")).scalar()
    product_names_count = session.query(ProductName).count()
    assert fts_count >= product_names_count
    distinct_indexed_products = session.execute(
        text("SELECT COUNT(DISTINCT product_id) FROM products_fts")
    ).scalar()
    assert distinct_indexed_products == session.query(Product).count()

    # 統計數字內部一致
    for s in snapshots:
        assert 0 <= s.new_products <= s.total_products
        assert s.delisted_products >= 0
        assert s.price_up_count >= 0
        assert s.price_down_count >= 0
