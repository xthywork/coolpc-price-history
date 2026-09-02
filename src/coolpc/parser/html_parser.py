from __future__ import annotations
import datetime
import re
from bs4 import BeautifulSoup
from coolpc.parser.models import ParseError

MDY_PATTERN = re.compile(r"(\d{4})/(\d{1,2})/(\d{1,2})\s+(\d{1,2}):(\d{2})")


def decode_html(raw_bytes: bytes) -> str:
    try:
        return raw_bytes.decode("big5", errors="replace")
    except LookupError as exc:
        raise ParseError(f"無法以 Big5 解碼: {exc}") from exc


def parse_fetched_at(soup: BeautifulSoup) -> datetime.datetime:
    node = soup.find(id="Mdy")
    if node is None:
        raise ParseError("找不到 #Mdy 估價時間欄位")
    m = MDY_PATTERN.search(node.get_text())
    if not m:
        raise ParseError(f"無法解析估價時間: {node.get_text()!r}")
    year, month, day, hour, minute = (int(g) for g in m.groups())
    return datetime.datetime(year, month, day, hour, minute)
