import pytest
from coolpc.parser.html_parser import parse_html
from coolpc.parser.models import ParseError

SAMPLE = "/home/xthybot/coolpc/download/2026-02-01-21-40.html"


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


def test_parse_html_does_not_duplicate_options_across_nested_optgroups():
    """真實 HTML 的 <optgroup> 沒有對應的 </optgroup> 結束標籤，lxml 會把後續
    每個 <optgroup> 都巢狀解析進前一個 <optgroup> 內，而不是視為兄弟節點。
    若用預設的 recursive=True 抓 <option>，同一個商品會被外層 optgroup 重複
    計入，導致單一份快照的商品數暴增到十萬筆等級（實際應為數千筆）。這裡
    驗證商品數量級合理，並且商品數應精確等於「未被停用且非彙總列(value=0)
    的 <option> 總數」（獨立於 parse_products 邏輯之外直接統計得出），確認
    沒有任何 <option> 被重複計入或漏算。"""
    with open(SAMPLE, "rb") as f:
        raw = f.read()
    from coolpc.parser.html_parser import decode_html
    from bs4 import BeautifulSoup

    soup = BeautifulSoup(decode_html(raw), "lxml")
    tbody = soup.find(id="tbdy")
    expected_candidate_count = 0
    for tr in tbody.find_all("tr", recursive=False):
        select = tr.find("select")
        if select is None:
            continue
        for optgroup in select.find_all("optgroup"):
            for opt in optgroup.find_all("option", recursive=False):
                if opt.has_attr("disabled") or opt.get("value") == "0":
                    continue
                expected_candidate_count += 1

    snapshot = parse_html(raw)

    # 修正前約 10 萬筆（每個 option 被多個外層 optgroup 重複計入），
    # 修正後應精確等於獨立統計出的候選 option 數量
    assert len(snapshot.products) == expected_candidate_count
    assert len(snapshot.products) < 20000
