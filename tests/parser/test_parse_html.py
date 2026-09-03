import os
import pytest
from coolpc.parser.html_parser import parse_html, decode_html, SUMMARY_COUNT_PATTERN
from coolpc.parser.models import ParseError
from bs4 import BeautifulSoup

# I10: 見 tests/test_regression_real_html.py 的說明。
SAMPLE_DIR = os.environ.get("COOLPC_SAMPLE_DIR", "/home/xthybot/coolpc/download")
if not os.path.isdir(SAMPLE_DIR):
    pytest.skip(f"real HTML corpus not found at {SAMPLE_DIR}", allow_module_level=True)
SAMPLE = f"{SAMPLE_DIR}/2026-02-01-21-40.html"
# 真實案例：這份快照的「滑鼠｜鼠墊｜數位板」分類，有 5 個羅技賽車方向盤
# <option> 直接是 <select> 的子節點，沒有被任何 <optgroup> 包住，出現在
# 第一個 <optgroup> 之前。
ORPHAN_OPTION_SAMPLE = f"{SAMPLE_DIR}/2026-05-05-18-00.html"


def test_parse_html_full_snapshot():
    with open(SAMPLE, "rb") as f:
        raw = f.read()
    snapshot = parse_html(raw)

    assert snapshot.fetched_at.year == 2026
    assert snapshot.fetched_at.month == 2
    assert snapshot.fetched_at.day == 1

    assert len(snapshot.products) > 5000

    categories = {p.category_name for p in snapshot.products}
    assert "顯示卡VGA" in categories
    assert "處理器 CPU" in categories

    vga = [p for p in snapshot.products if p.category_name == "顯示卡VGA"]
    assert len(vga) > 100
    for p in vga[:20]:
        assert p.price > 0
        assert "," not in p.name  # 名稱本體不應殘留切分用的逗號結構性錯誤
        assert "$" not in p.name


def test_parse_html_excludes_disabled_and_summary_options():
    with open(SAMPLE, "rb") as f:
        raw = f.read()
    snapshot = parse_html(raw)
    for p in snapshot.products:
        assert "此商品為專業性產品" not in p.name
        assert not p.name.startswith("共有商品")


def test_parse_html_raises_parse_error_on_garbage():
    with pytest.raises(ParseError):
        parse_html(b"<html><body>not a coolpc page</body></html>")


def test_parse_html_product_counts_match_page_reported_summary_totals():
    """獨立正確性驗證：每個分類的 <select> 開頭都有一個 value="0" 的
    「共有商品 N 樣...」彙總選項，是原價屋網站自己回報的商品總數。這裡拿
    parse_html 對每個分類解出的商品數，去跟這個「頁面自己講的數字」比對，
    而不是重用 parse_products 內部同一套 optgroup/option 走訪邏輯去算
    「預期值」——後者這種「獨立測試」其實是假的獨立：用同一套（可能有 bug
    的）走訪邏輯算出來的預期值，永遠會跟自己的輸出一致，完全抓不到「走訪
    邏輯本身漏看了哪些 <option>」這類 bug。真實案例：舊版走訪邏輯
    （select.find_all("optgroup") 再對每個 optgroup 分別找 option）完全看
    不到「沒有被任何 optgroup 包住、直接是 <select> 子節點」的孤兒 option
    （見 test_parse_html_includes_options_not_wrapped_in_any_optgroup），
    但因為舊版的「預期值」用的是同一套走訪邏輯，那個孤兒 option 在預期值
    跟實際值裡都一樣被漏掉，測試因此照樣通過，完全沒發現問題。
    這裡也同時涵蓋巢狀 optgroup 重複計算的 bug：若 option 被重複計入，
    parse_html 解出的數字就會遠大於頁面自己回報的「共有商品 N」。"""
    with open(SAMPLE, "rb") as f:
        raw = f.read()

    soup = BeautifulSoup(decode_html(raw), "lxml")
    tbody = soup.find(id="tbdy")
    expected_by_category = {}
    for tr in tbody.find_all("tr", recursive=False):
        tds = tr.find_all("td", recursive=False)
        if len(tds) < 2:
            continue
        cat = tds[1].get_text(strip=True)
        select = tr.find("select")
        if select is None:
            continue
        opt0 = select.find("option", attrs={"value": "0"})
        if opt0 is None:
            continue
        m = SUMMARY_COUNT_PATTERN.search(opt0.get_text())
        if not m:
            continue
        expected_by_category[cat] = int(m.group(1))

    assert len(expected_by_category) > 20  # 確保真的抓到大部分分類的彙總數字

    snapshot = parse_html(raw)
    actual_by_category = {}
    for p in snapshot.products:
        actual_by_category[p.category_name] = actual_by_category.get(p.category_name, 0) + 1

    mismatches = {
        cat: (expected, actual_by_category.get(cat, 0))
        for cat, expected in expected_by_category.items()
        if actual_by_category.get(cat, 0) != expected
    }
    assert mismatches == {}


def test_parse_html_includes_options_not_wrapped_in_any_optgroup():
    """真實案例：2026-05-05-18-00.html 的「滑鼠｜鼠墊｜數位板」分類，頁面
    自己回報「共有商品 316 樣」，但其中 5 個非停用、高單價的羅技賽車方向盤
    選項（G923/G RS50/G PRO 系列組合，最高 NT$42,900）直接是 <select> 的
    子節點，出現在第一個 <optgroup>（"【周邊活動促銷專區】"）之前，完全沒
    有被任何 <optgroup> 包住。舊版走訪邏輯
    （select.find_all("optgroup") 再對每個 optgroup 找 option）只會看到
    「巢狀在某個 optgroup 底下」的 option，這 5 個孤兒 option 完全不會被
    走訪到，導致該分類少算成 311 筆。"""
    with open(ORPHAN_OPTION_SAMPLE, "rb") as f:
        raw = f.read()
    snapshot = parse_html(raw)
    mouse = [p for p in snapshot.products if p.category_name == "滑鼠｜鼠墊｜數位板"]
    assert len(mouse) == 316

    names = {p.name for p in mouse}
    assert any("G923" in n for n in names)
    assert any("G RS50" in n for n in names)
    assert any("G PRO" in n for n in names)


def test_parse_html_strips_countdown_and_deal_deadline_from_all_names():
    """全語料庫回歸抽測發現促銷倒數/檔期到期日文字（"▼下殺到 M/D HH:MM"、
    "優惠至 M/D"、"活動至 M/D止"）會殘留在 name 尾端，且這些期限文字會隨著
    促銷檔期改變（同一個實體商品在不同快照出現不同期限），破壞「name 完全
    相等」的商品比對。這裡驗證整份快照解析後，沒有任何商品名稱殘留這些
    格式。"""
    with open(SAMPLE, "rb") as f:
        raw = f.read()
    snapshot = parse_html(raw)
    for p in snapshot.products:
        assert "下殺到" not in p.name
        assert "優惠至" not in p.name
        assert "活動至" not in p.name
