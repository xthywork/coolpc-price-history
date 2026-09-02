import datetime
import httpx
import pytest
from coolpc.scraper.fetcher import fetch_html, save_raw_html, FetchError

def test_fetch_html_returns_body_on_success():
    def handler(request):
        return httpx.Response(200, content="<html>ok 原價屋</html>".encode("cp950"))
    client = httpx.Client(transport=httpx.MockTransport(handler))
    result = fetch_html(url="https://coolpc.com.tw/evaluate.php", client=client)
    assert "原價屋" in result.decode("cp950")

def test_fetch_html_raises_fetch_error_on_http_status_error():
    def handler(request):
        return httpx.Response(500)
    client = httpx.Client(transport=httpx.MockTransport(handler))
    with pytest.raises(FetchError):
        fetch_html(url="https://coolpc.com.tw/evaluate.php", client=client)

def test_fetch_html_raises_fetch_error_on_connect_error():
    def handler(request):
        raise httpx.ConnectError("boom", request=request)
    client = httpx.Client(transport=httpx.MockTransport(handler))
    with pytest.raises(FetchError):
        fetch_html(url="https://coolpc.com.tw/evaluate.php", client=client)

def test_save_raw_html_writes_file_under_date_dir(tmp_path):
    fetched_at = datetime.datetime(2026, 2, 1, 21, 40, 0)
    path = save_raw_html(b"hello", fetched_at, base_dir=str(tmp_path))
    assert path.endswith("2026-02-01-21-40-00.html")
    assert "2026" in path and "02" in path and "01" in path
    with open(path, "rb") as f:
        assert f.read() == b"hello"
