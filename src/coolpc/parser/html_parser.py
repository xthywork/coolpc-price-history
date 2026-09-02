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


# 全語料庫（842 份樣本）掃描發現：原價屋會把「限時促銷倒數期限」直接黏在
# 商品名稱尾端、緊接在價格逗號之前，而且期限會隨著促銷檔期改變。因為本系統
# 的商品比對是「name 完全相等」（無自動合併），這種會變動的尾綴文字會讓
# 同一個實體商品在不同快照被誤判成不同商品，破壞價格歷史的連續性。
# 目前確認的兩種格式，兩種都已用全語料庫驗證「同一個商品、不同快照出現不同
# 期限文字」（真正的 volatile，不是單純猜測）：
#   1) "▼下殺到 M/D HH:MM"（限時下殺倒數），例如
#      "...DC15250-R4508STW▼下殺到 2/4 23:59, $21990↘$16999 ◆ ★"。
#      全語料庫累計 125,548 次、2,092 種不同商品名稱受影響；同一台螢幕在
#      某些快照是 "...▼下殺到 5/14 23:59"，另一些快照是
#      "...▼下殺到 5/17 23:59"。
#   2) "優惠至 M/D" / "活動至 M/D止"（任搭/組合優惠檔期到期日），例如
#      "...16+2+2相*任搭優惠至3/31"。全語料庫驗證：同一片主機板／顯卡在
#      不同快照分別出現過 "優惠至3/31"、"優惠至4/30"、"優惠至5/31"
#      （檔期展延時商品名稱字串跟著變動）。
# 這兩種格式都不含 $ 或箭頭符號，NAME_PRICE_* 系列的價格切分 regex 完全沒有
# 依據可以把它們跟真正的商品名稱分開，所以會被切進 name 裡。因此獨立於價格
# 切分之外，另外用一個專門的清理步驟把這些尾綴從 name 移除（在
# split_name_price_badges 完成價格切分「之後」才處理，這是名稱清理的關注點，
# 跟價格切分的關注點是分開的，不應該混進 NAME_PRICE_* regex 裡）。
#
# 另外全語料庫掃描還發現「限時」「春節限時」「限量活動」「酷幣5000」這類
# 行銷用語也會在同一個實體商品（同型號）身上時有時無、時換時異（例如同一台
# 華碩 Zenbook UX3407QA-0082G26100 曾出現過 "超輕盈 酷幣5000"、
# "超輕盈/春節限時"、"超輕盈/限量活動"、單純 "超輕盈" 四種不同尾綴），理論上
# 也會造成一樣的商品比對問題。但這類文字沒有像日期一樣的固定結構可以安全地
# 用 regex 辨識邊界（不同商品的分隔符號、用字都不一致，貿然用關鍵字比對可能
# 誤刪真正屬於商品名稱一部分的文字），所以這裡刻意不處理，記錄成已知風險，
# 留給之後專門處理「商品名稱正規化/相似度比對」的 Task（見 Task 10）評估。
PROMO_DEADLINE_SUFFIX_PATTERN = re.compile(
    r"(?:▼下殺到\s*\d{1,2}/\d{1,2}\s*\d{1,2}:\d{2}"
    r"|(?:優惠至|活動至)\s*\d{1,2}/\d{1,2}\s*止?)\s*$"
)


def strip_promo_deadline_suffix(name: str) -> str:
    # 少數情況下不同促銷機制可能疊加出現（例如同時有下殺倒數與任搭優惠
    # 期限），用迴圈重複套用直到沒有變化為止，避免只清掉最外層一次。
    while True:
        stripped = PROMO_DEADLINE_SUFFIX_PATTERN.sub("", name).strip()
        if stripped == name:
            return stripped
        name = stripped


# 每個 <select> 開頭都有一個 value="0" 的「共有商品 N 樣...」彙總選項，
# 用來驗證解析結果數量是否正確（見 test_parse_html.py 的獨立回歸測試）。
SUMMARY_COUNT_PATTERN = re.compile(r"共有商品\s*(\d+)")


def _iter_select_options(select):
    """走訪一個 <select> 底下所有 <option>，依文件順序 yield
    (subcategory_name, option) pair。

    真實 HTML 的 <optgroup> 沒有對應的 </optgroup> 結束標籤，lxml 會把後續
    每個 <optgroup> 都巢狀解析進前一個 <optgroup> 內（見上方 NAME_PRICE_*
    區塊的說明），所以不能只用 select.find_all("optgroup") 再對每個
    optgroup 呼叫 find_all("option", recursive=False)：這樣做完全看不到
    「不屬於任何 optgroup、直接是 <select> 子節點」的 <option>。

    全語料庫掃描發現至少一個真實案例（2026-05-05-18-00.html 的
    「滑鼠｜鼠墊｜數位板」分類）：5 個非停用、高單價的羅技賽車方向盤選項
    直接是 <select> 的子節點，出現在第一個 <optgroup>（例如
    "【周邊活動促銷專區】"）之前，完全沒有被任何 optgroup 包住。這類
    「孤兒」選項在文件順序上一定出現在「目前 select 內第一個 optgroup 標籤」
    之前（因為 lxml 的巢狀 bug 只會把後面的 optgroup 巢狀進第一個裡面，
    不會讓後面的 option 又跑到 select 的直接子節點層級）。

    做法：依文件順序遞迴走訪每一層的直接子節點（recursive=False 語意）。
    遇到 <option> 就用「目前累積到的 subcategory_name」（尚未遇到任何
    optgroup 時就是空字串，代表沒有分類）yield 出去；遇到 <optgroup> 就
    把 subcategory_name 更新成它的 label，然後遞迴進去繼續走訪它自己的
    直接子節點（這一層可能又是「它自己的孤兒 option」接著「下一個巢狀
    optgroup」，如此遞迴下去，剛好對應原始文件裡本來就是兄弟關係、只是
    被 lxml 誤判成巢狀的那條鏈）。
    """
    subcategory_name = ""
    for child in select.children:
        tag_name = getattr(child, "name", None)
        if tag_name == "option":
            yield subcategory_name, child
        elif tag_name == "optgroup":
            subcategory_name = child.get("label", "").strip()
            yield from _iter_select_options(child)


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
        for subcategory_name, opt in _iter_select_options(select):
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
            name = strip_promo_deadline_suffix(name)
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
