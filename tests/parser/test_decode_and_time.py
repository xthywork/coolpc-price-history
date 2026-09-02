import datetime
from bs4 import BeautifulSoup
from coolpc.parser.html_parser import decode_html, parse_fetched_at

SAMPLE = "/home/xthybot/coolpc/download/2026-02-01-21-40.html"

def test_decode_html_produces_correct_chinese_text():
    with open(SAMPLE, "rb") as f:
        raw = f.read()
    text = decode_html(raw)
    assert "原價屋線上估價" in text
    assert "顯示卡VGA" in text

def test_parse_fetched_at_reads_mdy_field():
    with open(SAMPLE, "rb") as f:
        raw = f.read()
    text = decode_html(raw)
    soup = BeautifulSoup(text, "lxml")
    fetched_at = parse_fetched_at(soup)
    assert fetched_at == datetime.datetime(2026, 2, 1, 14, 28)
