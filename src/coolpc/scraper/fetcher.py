from __future__ import annotations
import datetime
import os
import httpx

DEFAULT_URL = "https://coolpc.com.tw/evaluate.php"


class FetchError(Exception):
    pass


def get_evaluate_url() -> str:
    return os.environ.get("COOLPC_EVALUATE_URL", DEFAULT_URL)


def fetch_html(url: str | None = None, timeout: float = 30.0,
                client: httpx.Client | None = None) -> bytes:
    target = url or get_evaluate_url()
    owns_client = client is None
    client = client or httpx.Client()
    try:
        try:
            response = client.get(target, timeout=timeout, follow_redirects=True)
            response.raise_for_status()
        except httpx.HTTPStatusError as exc:
            raise FetchError(f"HTTP 錯誤 {exc.response.status_code}: {target}") from exc
        except httpx.RequestError as exc:
            raise FetchError(f"網路請求失敗: {exc}") from exc
        return response.content
    finally:
        if owns_client:
            client.close()


def save_raw_html(raw_bytes: bytes, fetched_at: datetime.datetime,
                   base_dir: str = "data/raw_html") -> str:
    day_dir = os.path.join(base_dir, f"{fetched_at:%Y}", f"{fetched_at:%m}", f"{fetched_at:%d}")
    os.makedirs(day_dir, exist_ok=True)
    filename = f"{fetched_at:%Y-%m-%d-%H-%M-%S}.html"
    path = os.path.join(day_dir, filename)
    with open(path, "wb") as f:
        f.write(raw_bytes)
    return path
