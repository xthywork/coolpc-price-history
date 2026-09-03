import os
import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from coolpc.db.models import Base, Category, ScrapeSnapshot
from coolpc.scraper.run import run_scrape, ScrapeSkipped
from coolpc.scraper.lock import ScraperLock
from coolpc.scraper.fetcher import FetchError

# I10: 見 tests/test_regression_real_html.py 的說明。
SAMPLE_DIR = os.environ.get("COOLPC_SAMPLE_DIR", "/home/xthybot/coolpc/download")
if not os.path.isdir(SAMPLE_DIR):
    pytest.skip(f"real HTML corpus not found at {SAMPLE_DIR}", allow_module_level=True)
SAMPLE = f"{SAMPLE_DIR}/2026-02-01-21-40.html"

def _session_factory():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    return sessionmaker(bind=engine)

def test_run_scrape_success(tmp_path, monkeypatch):
    with open(SAMPLE, "rb") as f:
        raw = f.read()
    monkeypatch.setattr("coolpc.scraper.run.fetch_html", lambda url=None: raw)
    snapshot = run_scrape(
        scrape_type="manual",
        session_factory=_session_factory(),
        lock_path=str(tmp_path / "s.lock"),
        raw_html_base_dir=str(tmp_path / "raw"),
    )
    assert snapshot.status == "success"
    assert snapshot.total_products > 5000
    assert snapshot.raw_html_path is not None
    import os
    assert os.path.exists(snapshot.raw_html_path)

def test_run_scrape_records_failure_on_fetch_error(tmp_path, monkeypatch):
    def raise_fetch_error(url=None):
        raise FetchError("網路失敗")
    monkeypatch.setattr("coolpc.scraper.run.fetch_html", raise_fetch_error)
    snapshot = run_scrape(
        scrape_type="scheduled",
        session_factory=_session_factory(),
        lock_path=str(tmp_path / "s.lock"),
        raw_html_base_dir=str(tmp_path / "raw"),
    )
    assert snapshot.status == "failed"
    assert "網路失敗" in snapshot.error_message
    assert snapshot.raw_html_path is None

def test_run_scrape_saves_html_and_records_failure_on_parse_error(tmp_path, monkeypatch):
    monkeypatch.setattr("coolpc.scraper.run.fetch_html",
                         lambda url=None: b"<html><body>not coolpc</body></html>")
    snapshot = run_scrape(
        scrape_type="scheduled",
        session_factory=_session_factory(),
        lock_path=str(tmp_path / "s.lock"),
        raw_html_base_dir=str(tmp_path / "raw"),
    )
    assert snapshot.status == "failed"
    assert snapshot.raw_html_path is not None
    import os
    assert os.path.exists(snapshot.raw_html_path)

def test_run_scrape_rolls_back_on_ingest_failure(tmp_path, monkeypatch):
    with open(SAMPLE, "rb") as f:
        raw = f.read()
    monkeypatch.setattr("coolpc.scraper.run.fetch_html", lambda url=None: raw)

    def fake_ingest_snapshot(session, parsed, scrape_type, raw_html_path):
        # 模擬 ingest 流程先寫入部分資料，才在中途失敗，
        # 驗證 run_scrape 會把整個 transaction rollback 掉，
        # 而不是留下部分寫入的髒資料。
        session.add(Category(name="__bogus_partial_write__"))
        session.flush()
        raise RuntimeError("模擬 ingest 失敗")

    monkeypatch.setattr("coolpc.scraper.run.ingest_snapshot", fake_ingest_snapshot)

    session_factory = _session_factory()
    lock_path = str(tmp_path / "s.lock")
    snapshot = run_scrape(
        scrape_type="manual",
        session_factory=session_factory,
        lock_path=lock_path,
        raw_html_base_dir=str(tmp_path / "raw"),
    )

    assert snapshot.status == "failed"
    assert "模擬 ingest 失敗" in snapshot.error_message
    # (d) 已下載成功的原始 HTML 仍應保留，不因 DB 寫入失敗而遺失
    assert snapshot.raw_html_path is not None
    assert os.path.exists(snapshot.raw_html_path)

    with session_factory() as session:
        # (b) rollback 後，ingest 中途寫入的部分資料不應殘留
        bogus_count = session.query(Category).filter_by(
            name="__bogus_partial_write__").count()
        assert bogus_count == 0
        # (c) 只留下一筆失敗快照紀錄
        failures = session.query(ScrapeSnapshot).filter_by(status="failed").all()
        assert len(failures) == 1

    # (e) 鎖檔案在失敗後仍會被釋放
    assert not os.path.exists(lock_path)


def test_run_scrape_skips_when_locked(tmp_path, monkeypatch):
    lock_path = str(tmp_path / "s.lock")
    holder = ScraperLock(lock_path)
    holder.acquire()
    try:
        monkeypatch.setattr("coolpc.scraper.run.fetch_html", lambda url=None: b"")
        try:
            run_scrape(scrape_type="manual", session_factory=_session_factory(),
                       lock_path=lock_path, raw_html_base_dir=str(tmp_path / "raw"))
            assert False, "應該要拋出 ScrapeSkipped"
        except ScrapeSkipped:
            pass
    finally:
        holder.release()
