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

def test_split_handles_bare_old_price_before_arrow_bundle_format():
    """真實資料第三種降價格式：原價完全沒有 $ 前綴，只有裸數字後面緊接箭頭，
    常見於「組合優惠」整機搭購方案（例如「微星 Raider/Cyborg/Katana + 威剛
    16G」系列）。例如 "...125290↘, $124000 ◆ ★"（原價 125290 沒有 $，
    新價 124000 才有 $）。"""
    name, price, badges = split_name_price_badges(
        "【組合優惠】微星 Raider Ultra 9 黑 B2WI-025TW+威剛16G 125290↘, $124000 ◆ ★"
    )
    assert name == "【組合優惠】微星 Raider Ultra 9 黑 B2WI-025TW+威剛16G"
    assert price == 124000
    assert badges == "◆ ★"
    assert "," not in name
    assert "$" not in name
    assert "↘" not in name

def test_split_takes_final_price_across_chained_price_drops():
    """真實資料存在連續兩次降價的情況（例如 BenQ 螢幕搭購方案），
    例如 "...$3988↘, $3188↘$2988 ◆ ★"，必須取「最後」一次（最低）的價格
    2988，而不是中間那次 3188，且 badges 不應殘留 "↘$2988" 之類的片段。"""
    name, price, badges = split_name_price_badges(
        "【主機搭購】BenQ GW2790〈2H1P/IPS/100Hz/含喇叭〉.光智慧2.0 $3988↘, $3188↘$2988 ◆ ★"
    )
    assert name == "【主機搭購】BenQ GW2790〈2H1P/IPS/100Hz/含喇叭〉.光智慧2.0"
    assert price == 2988
    assert badges == "◆ ★"

def test_split_does_not_mis_split_on_embedded_dollar_sign_in_name():
    """真實資料的重大陷阱：商品名稱本身就含有行銷用的「原價$1590」字樣
    （$ 前面沒有逗號，只是緊貼在中文字後面，且沒有箭頭符號），例如
    "...原價$1590, $1190 ◆ ★ 熱賣"。逗號才是唯一能區分「這是價格起點」
    與「名稱裡剛好有個 $ 符號」的依據，所以沒有箭頭時，逗號必須是必要
    （不可為可選），否則會把名稱內嵌的 "$1590" 誤判成價格（應為 1190）。"""
    name, price, badges = split_name_price_badges(
        "視博通 MW-III 顯卡長35/CPU高16.5/網孔面板+燈條/玻璃透側/E-ATX 原價$1590, $1190 ◆ ★ 熱賣"
    )
    assert name == "視博通 MW-III 顯卡長35/CPU高16.5/網孔面板+燈條/玻璃透側/E-ATX 原價$1590"
    assert price == 1190
    assert badges == "◆ ★ 熱賣"

def test_split_handles_up_arrow_price_increase_warning():
    """真實資料還有一種與「↘ 降價」對稱的「↗ 漲價預告」格式，
    例如 "...(AD5U56008G-S), $2999↗$3099 ◆ ★"，常見於記憶體類商品，
    提醒買家即將漲價。目前實際在賣的價格是箭頭「前」的 2999，
    箭頭與未來價 3099 都應從 badges 消掉，不應殘留。"""
    name, price, badges = split_name_price_badges(
        "威剛 單條8GB D5-5600/CL46 (AD5U56008G-S), $2999↗$3099 ◆ ★"
    )
    assert name == "威剛 單條8GB D5-5600/CL46 (AD5U56008G-S)"
    assert price == 2999
    assert badges == "◆ ★"


def test_extract_status_finds_in_stock():
    assert extract_status("GIGABYTE 連接線【現貨】") == "現貨"

def test_extract_status_finds_order():
    assert extract_status("NVIDIA DGX Spark Cable 40 CM【訂】") == "訂"

def test_extract_status_ignores_non_status_bracket():
    assert extract_status("Synology HAT3300 4TB【限搭NAS主機】") is None

def test_extract_status_none_when_absent():
    assert extract_status("酷碼 VGA Holder 顯卡用支架 千斤頂顯卡支撐架/(0005-KUH00)") is None
