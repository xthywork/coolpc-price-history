from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from coolpc.db.models import Base
from coolpc.scraper.run import run_scrape, ScrapeSkipped
from coolpc.scraper.lock import ScraperLock
from coolpc.scraper.fetcher import FetchError

SAMPLE = "/home/xthybot/coolpc/download/2026-02-01-21-40.html"

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
