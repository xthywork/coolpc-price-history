import datetime
import os
import pytest
from bs4 import BeautifulSoup
from coolpc.parser.html_parser import decode_html, parse_fetched_at
from coolpc.parser.models import ParseError

# I10: 見 tests/test_regression_real_html.py 的說明。
SAMPLE_DIR = os.environ.get("COOLPC_SAMPLE_DIR", "/home/xthybot/coolpc/download")
if not os.path.isdir(SAMPLE_DIR):
    pytest.skip(f"real HTML corpus not found at {SAMPLE_DIR}", allow_module_level=True)
SAMPLE = f"{SAMPLE_DIR}/2026-02-01-21-40.html"

def test_decode_html_produces_correct_chinese_text():
    with open(SAMPLE, "rb") as f:
        raw = f.read()
    text = decode_html(raw)
    assert "原價屋線上估價" in text
    assert "顯示卡VGA" in text

def test_decode_html_correctly_decodes_eten_extension_characters():
    # 迴歸測試：Python 內建 "big5" codec 無法涵蓋 ETen 廠商擴充字元，
    # 會把「宏碁」錯誤解碼成「宏??」等亂碼（此樣本中共 138 個替代字元）。
    # cp950 才是正確的 Big5 (Windows/廠商擴充) 變體，此樣本僅剩 1 個替代字元。
    with open(SAMPLE, "rb") as f:
        raw = f.read()
    text = decode_html(raw)
    assert "宏碁" in text
    assert text.count("�") <= 1

def test_parse_fetched_at_reads_mdy_field():
    with open(SAMPLE, "rb") as f:
        raw = f.read()
    text = decode_html(raw)
    soup = BeautifulSoup(text, "lxml")
    fetched_at = parse_fetched_at(soup)
    assert fetched_at == datetime.datetime(2026, 2, 1, 14, 28)

def test_parse_fetched_at_raises_when_mdy_element_missing():
    soup = BeautifulSoup("<html><body><p>沒有 Mdy 欄位</p></body></html>", "lxml")
    with pytest.raises(ParseError):
        parse_fetched_at(soup)

@pytest.mark.parametrize("garbage_text", ["", "não é uma data", "2026年2月1日 下午2點28分"])
def test_parse_fetched_at_raises_when_mdy_text_unparseable(garbage_text):
    soup = BeautifulSoup(f'<html><body><font id="Mdy">{garbage_text}</font></body></html>', "lxml")
    with pytest.raises(ParseError):
        parse_fetched_at(soup)
