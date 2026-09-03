import glob
import os
import shutil
import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from coolpc.db.models import Base, Product
from coolpc.scraper.run import import_html_file, import_html_dir

# I10: 見 tests/test_regression_real_html.py 的說明。
SAMPLE_DIR = os.environ.get("COOLPC_SAMPLE_DIR", "/home/xthybot/coolpc/download")
if not os.path.isdir(SAMPLE_DIR):
    pytest.skip(f"real HTML corpus not found at {SAMPLE_DIR}", allow_module_level=True)

def _session_factory():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    return sessionmaker(bind=engine)

def test_import_html_file_uses_html_embedded_time():
    sf = _session_factory()
    snapshot = import_html_file(f"{SAMPLE_DIR}/2026-02-01-21-40.html", session_factory=sf)
    assert snapshot.status == "success"
    assert (snapshot.fetched_at.year, snapshot.fetched_at.month, snapshot.fetched_at.day) == (2026, 2, 1)
    assert snapshot.scrape_type == "import"
    assert snapshot.raw_html_path == f"{SAMPLE_DIR}/2026-02-01-21-40.html"

def test_import_html_dir_processes_in_chronological_order(tmp_path):
    files = sorted(glob.glob(f"{SAMPLE_DIR}/*.html"))[:3]
    for f in files:
        shutil.copy(f, tmp_path)
    sf = _session_factory()
    snapshots = import_html_dir(str(tmp_path), session_factory=sf)
    assert len(snapshots) == 3
    assert all(s.status == "success" for s in snapshots)
    fetched_times = [s.fetched_at for s in snapshots]
    assert fetched_times == sorted(fetched_times)
    with sf() as session:
        assert session.query(Product).count() > 0

def test_import_html_file_records_failure_without_losing_existing_data():
    sf = _session_factory()
    ok = import_html_file(f"{SAMPLE_DIR}/2026-02-01-21-40.html", session_factory=sf)
    assert ok.status == "success"
    with sf() as session:
        before = session.query(Product).count()

    import tempfile, os
    with tempfile.NamedTemporaryFile(suffix=".html", delete=False) as f:
        f.write(b"<html><body>garbage</body></html>")
        bad_path = f.name
    try:
        failed = import_html_file(bad_path, session_factory=sf)
        assert failed.status == "failed"
    finally:
        os.remove(bad_path)

    with sf() as session:
        after = session.query(Product).count()
    assert after == before
