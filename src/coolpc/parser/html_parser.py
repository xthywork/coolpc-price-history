from __future__ import annotations
import datetime
import re
from bs4 import BeautifulSoup
from coolpc.parser.models import ParseError, ParsedProduct, ParsedSnapshot

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


# 真實資料有兩種降價格式：
#   1) "NAME, $原價↘$新價 標記"（逗號在原價之前，箭頭與新價之間無逗號）
#   2) "NAME $原價↘, $新價 標記"（原價前無逗號，逗號在箭頭與新價之間，
#      常見於「搭購」組合優惠）
# 用 \s*,?\s*\$ 讓「逗號」在名稱與價格之間、以及箭頭與新價之間都是可選的，
# 兩種格式都能正確切出名稱（不殘留價格片段）。
NAME_PRICE_PATTERN = re.compile(r"^(.*?)\s*,?\s*\$([\d,]+)(?:↘\s*,?\s*\$([\d,]+))?\s*(.*)$", re.S)
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


def parse_products(soup: BeautifulSoup) -> list[ParsedProduct]:
    tbody = soup.find(id="tbdy")
    if tbody is None:
        raise ParseError("找不到 #tbdy 商品表格")

    products: list[ParsedProduct] = []
    for tr in tbody.find_all("tr", recursive=False):
        tds = tr.find_all("td", recursive=False)
        if len(tds) < 3:
            continue
        category_name = tds[1].get_text(strip=True)
        select = tr.find("select")
        if select is None:
            continue
        for optgroup in select.find_all("optgroup"):
            subcategory_name = optgroup.get("label", "").strip()
            # 真實 HTML 的 <optgroup> 沒有對應的 </optgroup> 結束標籤；
            # lxml 依 HTML5 規則本應在遇到下一個 <optgroup> 時隱式關閉前一個
            # （使其成為兄弟節點），但實測會把後續每個 <optgroup> 都巢狀
            # 解析進前一個 <optgroup> 內。若這裡用預設的 recursive=True，
            # find_all("option") 會把子孫層所有巢狀 optgroup 的 <option>
            # 也一併抓進來，導致同一個 <option> 被計入多個（外層）optgroup，
            # 商品數暴增數十倍且 subcategory_name 被誤植為外層分類。
            # 用 recursive=False 只取「緊接在這個 optgroup 開始標籤之後、
            # 下一個巢狀 optgroup 之前」的 <option>，才是它真正對應的商品。
            for opt in optgroup.find_all("option", recursive=False):
                if opt.has_attr("disabled"):
                    continue
                if opt.get("value") == "0":
                    continue
                text = opt.get_text(strip=True)
                if ", $" not in text:
                    continue
                try:
                    name, price, badges = split_name_price_badges(text)
                except ParseError:
                    continue
                status = extract_status(name)
                products.append(ParsedProduct(
                    category_name=category_name,
                    subcategory_name=subcategory_name,
                    name=name,
                    price=price,
                    status=status,
                    badges=badges,
                ))
    return products


def parse_html(raw_bytes: bytes) -> ParsedSnapshot:
    text = decode_html(raw_bytes)
    soup = BeautifulSoup(text, "lxml")
    fetched_at = parse_fetched_at(soup)
    products = parse_products(soup)
    if not products:
        raise ParseError("解析結果沒有任何商品，HTML 結構可能已變更")
    return ParsedSnapshot(fetched_at=fetched_at, products=products)
