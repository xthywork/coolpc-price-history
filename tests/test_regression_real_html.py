import glob
import os
import subprocess
import sys
import pytest
from sqlalchemy import create_engine, func
from sqlalchemy.orm import Session
from coolpc.db.models import Product, ProductName, PriceHistory, Category
from coolpc.parser.html_parser import parse_html
from coolpc.ingest.service import ingest_snapshot

# I10: 這份端對端回歸測試需要一份不在版本控制內的真實原價屋 HTML 語料庫。
# 預設路徑只在原作者的開發機上存在；其他機器（CI、其他開發者）應該可以
# 透過環境變數指定語料庫位置，找不到時要 skip 而不是直接測試失敗。
SAMPLE_DIR = os.environ.get("COOLPC_SAMPLE_DIR", "/home/xthybot/coolpc/download")
if not os.path.isdir(SAMPLE_DIR):
    pytest.skip(f"real HTML corpus not found at {SAMPLE_DIR}", allow_module_level=True)


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

    # 統計數字內部一致
    for s in snapshots:
        assert 0 <= s.new_products <= s.total_products
        assert s.delisted_products >= 0
        assert s.price_up_count >= 0
        assert s.price_down_count >= 0
