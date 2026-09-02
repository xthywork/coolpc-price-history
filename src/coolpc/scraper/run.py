from __future__ import annotations
import datetime
import glob
import os
from sqlalchemy.orm import sessionmaker, Session
from coolpc.db.session import get_engine, get_session_factory
from coolpc.db.models import ScrapeSnapshot
from coolpc.parser.html_parser import parse_html
from coolpc.parser.models import ParseError
from coolpc.ingest.service import ingest_snapshot
from coolpc.scraper.fetcher import fetch_html, save_raw_html, FetchError
from coolpc.scraper.lock import ScraperLock


class ScrapeSkipped(Exception):
    pass


def _record_failure(session_factory: sessionmaker[Session], scrape_type: str,
                     error_message: str, raw_html_path: str | None) -> ScrapeSnapshot:
    with session_factory() as session:
        snapshot = ScrapeSnapshot(
            fetched_at=datetime.datetime.utcnow(), scrape_type=scrape_type,
            raw_html_path=raw_html_path, status="failed", error_message=error_message,
            created_at=datetime.datetime.utcnow(),
        )
        session.add(snapshot)
        session.commit()
        session.refresh(snapshot)
        return snapshot


def run_scrape(
    scrape_type: str = "scheduled",
    session_factory: sessionmaker[Session] | None = None,
    url: str | None = None,
    lock_path: str = "data/scraper.lock",
    raw_html_base_dir: str = "data/raw_html",
) -> ScrapeSnapshot:
    session_factory = session_factory or get_session_factory(get_engine())
    lock = ScraperLock(lock_path)
    if not lock.acquire():
        raise ScrapeSkipped("已有抓取程序正在執行中，本次跳過")
    try:
        try:
            raw_bytes = fetch_html(url=url)
        except FetchError as exc:
            return _record_failure(session_factory, scrape_type, str(exc), None)

        try:
            parsed = parse_html(raw_bytes)
        except ParseError as exc:
            raw_html_path = save_raw_html(raw_bytes, datetime.datetime.utcnow(),
                                           base_dir=raw_html_base_dir)
            return _record_failure(session_factory, scrape_type, str(exc), raw_html_path)

        raw_html_path = save_raw_html(raw_bytes, parsed.fetched_at, base_dir=raw_html_base_dir)

        with session_factory() as session:
            try:
                snapshot = ingest_snapshot(session, parsed, scrape_type, raw_html_path)
                session.commit()
                session.refresh(snapshot)
                return snapshot
            except Exception as exc:
                session.rollback()
                return _record_failure(session_factory, scrape_type, str(exc), raw_html_path)
    finally:
        lock.release()


def import_html_file(path: str, session_factory: sessionmaker[Session] | None = None) -> ScrapeSnapshot:
    session_factory = session_factory or get_session_factory(get_engine())
    with open(path, "rb") as f:
        raw_bytes = f.read()
    try:
        parsed = parse_html(raw_bytes)
    except ParseError as exc:
        return _record_failure(session_factory, "import", str(exc), path)

    with session_factory() as session:
        try:
            snapshot = ingest_snapshot(session, parsed, "import", path)
            session.commit()
            session.refresh(snapshot)
            return snapshot
        except Exception as exc:
            session.rollback()
            return _record_failure(session_factory, "import", str(exc), path)


def import_html_dir(dir_path: str,
                     session_factory: sessionmaker[Session] | None = None) -> list[ScrapeSnapshot]:
    session_factory = session_factory or get_session_factory(get_engine())
    files = sorted(glob.glob(os.path.join(dir_path, "**", "*.html"), recursive=True))
    return [import_html_file(path, session_factory=session_factory) for path in files]
