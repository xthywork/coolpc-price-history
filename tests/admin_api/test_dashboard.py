import datetime
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool
from coolpc.db.models import Base, ScrapeSnapshot
from coolpc.admin_api.app import app
from coolpc.admin_api.dependencies import get_session


def _make_client():
    engine = create_engine(
        "sqlite:///:memory:", connect_args={"check_same_thread": False}, poolclass=StaticPool
    )
    Base.metadata.create_all(engine)
    TestingSession = sessionmaker(bind=engine)

    def override_get_session():
        session = TestingSession()
        try:
            yield session
        finally:
            session.close()

    app.dependency_overrides[get_session] = override_get_session
    return TestClient(app), TestingSession


def test_dashboard_shows_recent_snapshots():
    client, Session_ = _make_client()
    t = datetime.datetime(2026, 2, 1)
    with Session_() as session:
        session.add(ScrapeSnapshot(
            fetched_at=t, scrape_type="scheduled", raw_html_path="/x/2026-02-01.html",
            status="success", total_products=5000, new_products=10, delisted_products=3,
            price_up_count=20, price_down_count=15, created_at=t,
        ))
        session.commit()

    resp = client.get("/")
    assert resp.status_code == 200
    assert "success" in resp.text
    assert "5000" in resp.text


def test_manual_scrape_triggers_run_scrape_and_redirects(monkeypatch):
    client, Session_ = _make_client()
    called = {}

    def fake_run_scrape(scrape_type="scheduled", **kwargs):
        called["scrape_type"] = scrape_type
        return ScrapeSnapshot(
            fetched_at=datetime.datetime(2026, 2, 1), scrape_type=scrape_type,
            raw_html_path=None, status="success", total_products=1, new_products=1,
            delisted_products=0, price_up_count=0, price_down_count=0,
            created_at=datetime.datetime(2026, 2, 1),
        )

    monkeypatch.setattr("coolpc.admin_api.routers.dashboard.run_scrape", fake_run_scrape)
    resp = client.post("/scrape", follow_redirects=False)
    assert resp.status_code == 303
    assert called["scrape_type"] == "manual"


def test_html_archive_list_and_view(tmp_path):
    client, Session_ = _make_client()
    html_path = tmp_path / "sample.html"
    html_path.write_bytes("<html>測試內容 <script>alert(1)</script></html>".encode("cp950"))
    t = datetime.datetime(2026, 2, 1)
    with Session_() as session:
        snap = ScrapeSnapshot(
            fetched_at=t, scrape_type="manual", raw_html_path=str(html_path),
            status="success", total_products=1, created_at=t,
        )
        session.add(snap)
        session.commit()
        sid = snap.id

    list_resp = client.get("/html-archive")
    assert list_resp.status_code == 200
    assert str(html_path) in list_resp.text

    view_resp = client.get(f"/html-archive/{sid}")
    assert view_resp.status_code == 200
    assert "測試內容" in view_resp.text
    assert "<script>alert(1)</script>" not in view_resp.text  # 必須被跳脫，不可執行

def test_html_archive_view_404_for_missing():
    client, _ = _make_client()
    resp = client.get("/html-archive/999")
    assert resp.status_code == 404
