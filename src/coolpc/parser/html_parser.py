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


# 真實資料的降價格式：
#   1) "NAME, $原價↘$新價 標記"（逗號在原價之前，箭頭與新價之間無逗號）
#   2) "NAME $原價↘, $新價 標記"（原價前無逗號，逗號在箭頭與新價之間，
#      常見於「搭購」組合優惠）
#   3) "NAME 原價(無 $ 前綴)↘, $新價 標記"（原價完全沒有 $ 符號，只有裸數字，
#      常見於「組合優惠」整機搭購方案，如「微星 Raider/Cyborg/Katana + 威剛
#      16G」系列）
#   4) 連續降價："NAME $價1↘, $價2↘$價3 標記"（同一商品出現兩次以上的箭頭
#      降價，須取「最後」一次的價格，例如 BenQ 螢幕的搭購方案）
# 格式 3 的「裸數字」只有在後面緊接箭頭符號 ↘ 時才視為原價，避免誤吃一般
# 商品名稱結尾剛好是數字（例如型號）但其實沒有降價的情況——箭頭字元在真實
# 資料中只會出現在降價標記，是可靠的判斷依據。
#
# 全語料庫（842 份樣本）掃描曾發現一個更嚴重的真實案例：商品名稱本身就含有
# 行銷用的「原價$1590」字樣（$ 前面沒有逗號，只是緊貼在中文字後面），例如
# "...原價$1590, $1190 ◆ ★ 熱賣"。若把「NAME 前面的逗號」也設成可選
# （之前 NAME_PRICE_PLAIN_PATTERN 曾經這樣做，是為了處理沒有箭頭的簡單案例
# 誤帶入的舊假設），regex 會把名稱內嵌的 "$1590" 誤判成價格起點，切出錯誤
# 的價格（1590 而非真正在賣的 1190）且把逗號之後的真正價格片段殘留進
# badges。真正安全的判斷依據是：
#   - 有箭頭（↘）時，箭頭本身就是可靠的價格標記，箭頭前的價格可以沒有逗號
#     （對應格式 2/3/4）；
#   - 沒有箭頭時，逗號是唯一能區分「這是價格起點」與「名稱裡剛好有個 $ 符號」
#     的依據，因此逗號必須是必要（mandatory），不可省略。
# 因此拆成兩個子規則，先試「有箭頭」規則（逗號可省略，但箭頭必要，且用
# `(?:...)+` 讓箭頭段可重複出現、只保留最後一次的擷取值，處理格式 4 的連續
# 降價），找不到才退回「無箭頭、逗號必要、純 $價錢」規則。
NAME_PRICE_ARROW_PATTERN = re.compile(
    r"^(.*?)\s*,?\s*(?:\$([\d,]+)|(\d[\d,]{2,}))(?:↘\s*,?\s*\$([\d,]+))+\s*(.*)$", re.S
)
# 另有一種與「↘ 降價」對稱的「↗ 漲價預告」格式："NAME, $現價↗$未來價 標記"
# （現價前有逗號，箭頭與未來價之間沒有逗號），全語料庫掃描出現超過 5 萬次，
# 常見於記憶體類商品（提醒買家即將漲價）。這裡取箭頭「前」的現價（也就是
# 目前實際在賣的價格），並把箭頭與未來價一併從 badges 中消掉，避免殘留
# "↗$3099" 這類價格片段污染 badges 欄位。掃描全語料庫確認 ↗ 與 ↘ 不會同時
# 出現在同一段文字，也沒有連續多次 ↗ 的情況，所以不需要像 ↘ 一樣用可重複
# 的 group。
NAME_PRICE_UP_ARROW_PATTERN = re.compile(
    r"^(.*?)\s*,?\s*\$([\d,]+)↗\s*,?\s*\$([\d,]+)\s*(.*)$", re.S
)
NAME_PRICE_PLAIN_PATTERN = re.compile(r"^(.*?),\s*\$([\d,]+)\s*(.*)$", re.S)
STATUS_KEYWORDS = ["現貨", "訂", "客訂", "拆封品"]
STATUS_BRACKET_PATTERN = re.compile(r"[【｛]([^】｝]*)[】｝]")


def split_name_price_badges(option_text: str) -> tuple[str, int, str]:
    text = option_text.strip()
    m = NAME_PRICE_ARROW_PATTERN.match(text)
    if m:
        name = m.group(1).strip()
        price = int(m.group(4).replace(",", ""))
        badges = m.group(5).strip()
        return name, price, badges
    m = NAME_PRICE_UP_ARROW_PATTERN.match(text)
    if m:
        name = m.group(1).strip()
        price = int(m.group(2).replace(",", ""))
        badges = m.group(4).strip()
        return name, price, badges
    m = NAME_PRICE_PLAIN_PATTERN.match(text)
    if not m:
        raise ParseError(f"無法從商品文字切出名稱/價格: {text!r}")
    name = m.group(1).strip()
    price = int(m.group(2).replace(",", ""))
    badges = m.group(3).strip()
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
