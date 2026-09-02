import pytest
from coolpc.parser.html_parser import split_name_price_badges, extract_status
from coolpc.parser.models import ParseError

def test_split_basic_product():
    name, price, badges = split_name_price_badges(
        "GIGABYTE AI TOP NVIDIA ConnectX-7 連接線【現貨】, $3990 ★"
    )
    assert name == "GIGABYTE AI TOP NVIDIA ConnectX-7 連接線【現貨】"
    assert price == 3990
    assert badges == "★"

def test_split_with_hot_sale_and_bundle_badges():
    name, price, badges = split_name_price_badges(
        "Acer Nitro ARC B580 OC 12GB(2740MHz/27cm/雙風扇/註三年), $8490 ★ 熱賣"
    )
    assert name == "Acer Nitro ARC B580 OC 12GB(2740MHz/27cm/雙風扇/註三年)"
    assert price == 8490
    assert badges == "★ 熱賣"

def test_split_with_price_drop_prefix():
    name, price, badges = split_name_price_badges(
        "華擎 ARC B580 Challenger 12G OC(2740MHz/25cm/雙風扇/註三年), $9290↘$8990 ◆ ★"
    )
    assert name == "華擎 ARC B580 Challenger 12G OC(2740MHz/25cm/雙風扇/註三年)"
    assert price == 8990
    assert badges == "◆ ★"

def test_split_raises_on_malformed_text():
    with pytest.raises(ParseError):
        split_name_price_badges("這不是一個有效的商品字串")

def test_split_handles_arrow_before_comma_bundle_format():
    """真實資料另一種降價格式：逗號在箭頭之後而非之前（常見於「搭購」組合優惠），
    例如 "...$2,799↘, $1499 ★"（原價前沒有逗號，逗號出現在箭頭與新價之間）。"""
    name, price, badges = split_name_price_badges(
        "【螢幕搭購】Raymii LS5U (單螢幕/穿夾兩用/高負重氣壓/17-43吋/承載18KG) $2,799↘, $1499 ★"
    )
    assert name == "【螢幕搭購】Raymii LS5U (單螢幕/穿夾兩用/高負重氣壓/17-43吋/承載18KG)"
    assert price == 1499
    assert badges == "★"

def test_split_handles_arrow_before_comma_bundle_format_with_multiple_badges():
    name, price, badges = split_name_price_badges(
        "【主機搭購】PHILIPS 27E2G2200〈1H1P/IPS/144Hz/HDR10〉$2988↘, $2788 ◆ ★"
    )
    assert name == "【主機搭購】PHILIPS 27E2G2200〈1H1P/IPS/144Hz/HDR10〉"
    assert price == 2788
    assert badges == "◆ ★"

def test_extract_status_finds_in_stock():
    assert extract_status("GIGABYTE 連接線【現貨】") == "現貨"

def test_extract_status_finds_order():
    assert extract_status("NVIDIA DGX Spark Cable 40 CM【訂】") == "訂"

def test_extract_status_ignores_non_status_bracket():
    assert extract_status("Synology HAT3300 4TB【限搭NAS主機】") is None

def test_extract_status_none_when_absent():
    assert extract_status("酷碼 VGA Holder 顯卡用支架 千斤頂顯卡支撐架/(0005-KUH00)") is None
