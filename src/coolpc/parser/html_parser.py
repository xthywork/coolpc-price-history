from __future__ import annotations
import datetime
import re
from bs4 import BeautifulSoup
from coolpc.parser.models import ParseError

MDY_PATTERN = re.compile(r"(\d{4})/(\d{1,2})/(\d{1,2})\s+(\d{1,2}):(\d{2})")


def decode_html(raw_bytes: bytes) -> str:
    try:
        return raw_bytes.decode("cp950", errors="replace")
    except LookupError as exc:
        raise ParseError(f"無法以 Big5 (cp950) 解碼: {exc}") from exc


def parse_fetched_at(soup: BeautifulSoup) -> datetime.datetime:
    node = soup.find(id="Mdy")
    if node is None:
        raise ParseError("找不到 #Mdy 估價時間欄位")
    m = MDY_PATTERN.search(node.get_text())
    if not m:
        raise ParseError(f"無法解析估價時間: {node.get_text()!r}")
    year, month, day, hour, minute = (int(g) for g in m.groups())
    return datetime.datetime(year, month, day, hour, minute)


NAME_PRICE_PATTERN = re.compile(r"^(.*?),\s*\$([\d,]+)(?:↘\$([\d,]+))?\s*(.*)$", re.S)
STATUS_KEYWORDS = ["現貨", "訂", "客訂", "拆封品"]
STATUS_BRACKET_PATTERN = re.compile(r"[【｛]([^】｝]*)[】｝]")


def split_name_price_badges(option_text: str) -> tuple[str, int, str]:
    text = option_text.strip()
    m = NAME_PRICE_PATTERN.match(text)
    if not m:
        raise ParseError(f"無法從商品文字切出名稱/價格: {text!r}")
    name = m.group(1).strip()
    final_price_str = m.group(3) or m.group(2)
    price = int(final_price_str.replace(",", ""))
    badges = m.group(4).strip()
    return name, price, badges


def extract_status(name: str) -> str | None:
    brackets = STATUS_BRACKET_PATTERN.findall(name)
    for content in reversed(brackets):
        if content in STATUS_KEYWORDS:
            return content
    return None
