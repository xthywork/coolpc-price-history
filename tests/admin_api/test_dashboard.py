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
    assert "5,000" in resp.text


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


def test_dashboard_row_carries_html_path_and_links_to_the_view(tmp_path):
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

    # 原本的 /html-archive 列表頁已移除：它跟抓取狀態頁列的是同一批東西
    assert client.get("/html-archive").status_code == 404
    assert "/html-archive\"" not in client.get("/").text

    # 檔案路徑改掛在抓取狀態那一列上，滑鼠停住就看得到；估價時間連進檢視頁
    dashboard_resp = client.get("/")
    assert dashboard_resp.status_code == 200
    assert f'title="原始 HTML：{html_path}"' in dashboard_resp.text
    assert f'href="/html-archive/{sid}"' in dashboard_resp.text

    view_resp = client.get(f"/html-archive/{sid}")
    assert view_resp.status_code == 200
    assert "測試內容" in view_resp.text
    assert "<script>alert(1)</script>" not in view_resp.text  # 必須被跳脫，不可執行

def test_html_archive_view_404_for_missing():
    client, _ = _make_client()
    resp = client.get("/html-archive/999")
    assert resp.status_code == 404


def _seed_snapshots(Session_, count: int):
    base = datetime.datetime(2026, 2, 1)
    with Session_() as session:
        for i in range(count):
            t = base + datetime.timedelta(hours=i)
            session.add(ScrapeSnapshot(
                fetched_at=t, scrape_type="scheduled", raw_html_path=f"/x/{i}.html",
                status="success", total_products=1000 + i, new_products=0, delisted_products=0,
                price_up_count=0, price_down_count=0, created_at=t,
            ))
        session.commit()


def test_dashboard_paginates_like_the_search_results():
    """抓取狀態頁要能翻到所有歷史紀錄，不是只看得到最近固定幾筆。"""
    client, Session_ = _make_client()
    _seed_snapshots(Session_, 45)

    resp = client.get("/", params={"page_size": "10"})
    assert resp.status_code == 200
    # 跟搜尋結果同一套分頁元件
    assert 'class="pagination__pages"' in resp.text
    assert 'id="jumpPageInput"' in resp.text
    assert 'id="pageSizeSelect"' in resp.text
    # 45 筆、每頁 10 筆 -> 5 頁，中間頁碼要能直接點
    assert "page=3" in resp.text
    assert "page=5" in resp.text
    assert 'max="5"' in resp.text
    assert "／ 5 頁" in resp.text
    # 總筆數顯示的是全部，不是這一頁的筆數
    assert "45 次" in resp.text


def test_dashboard_page_two_shows_different_snapshots():
    client, Session_ = _make_client()
    _seed_snapshots(Session_, 30)

    first = client.get("/", params={"page_size": "10", "page": 1})
    second = client.get("/", params={"page_size": "10", "page": 2})
    assert first.status_code == 200 and second.status_code == 200
    # 依 created_at 由新到舊，第一頁是最新的 10 筆
    assert "2026-02-02 05:00" in first.text
    assert "2026-02-02 05:00" not in second.text
    assert "2026-02-01 19:00" in second.text


def test_dashboard_page_size_all_lists_every_snapshot():
    client, Session_ = _make_client()
    _seed_snapshots(Session_, 30)

    resp = client.get("/", params={"page_size": "all"})
    assert resp.status_code == 200
    assert resp.text.count('<span class="status status-success">') == 30
