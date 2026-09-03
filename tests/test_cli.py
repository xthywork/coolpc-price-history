import os
import pytest
from coolpc.cli import main
from coolpc.db.session import get_engine
from coolpc.db.models import Base

# I10: 見 tests/test_regression_real_html.py 的說明——這些測試需要一份不在
# 版本控制內的真實原價屋 HTML 樣本，預設路徑只在原作者的開發機上存在。
SAMPLE_DIR = os.environ.get("COOLPC_SAMPLE_DIR", "/home/xthybot/coolpc/download")
if not os.path.isdir(SAMPLE_DIR):
    pytest.skip(f"real HTML corpus not found at {SAMPLE_DIR}", allow_module_level=True)
SAMPLE = f"{SAMPLE_DIR}/2026-02-01-21-40.html"


def _init_db(tmp_path, monkeypatch):
    monkeypatch.setenv("COOLPC_DB_PATH", str(tmp_path / "cli.db"))
    monkeypatch.chdir(tmp_path)
    Base.metadata.create_all(get_engine())


def test_cli_import_html_success_prints_summary(tmp_path, monkeypatch, capsys):
    _init_db(tmp_path, monkeypatch)
    exit_code = main(["import-html", SAMPLE])
    assert exit_code == 0
    out = capsys.readouterr().out
    assert "[success]" in out

def test_cli_import_dir(tmp_path, monkeypatch, capsys):
    import shutil
    _init_db(tmp_path, monkeypatch)
    html_dir = tmp_path / "html"
    html_dir.mkdir()
    shutil.copy(SAMPLE, html_dir)
    exit_code = main(["import-dir", str(html_dir)])
    assert exit_code == 0
    assert "[success]" in capsys.readouterr().out

def test_cli_scrape_returns_nonzero_on_fetch_failure(tmp_path, monkeypatch, capsys):
    _init_db(tmp_path, monkeypatch)
    monkeypatch.setenv("COOLPC_EVALUATE_URL", "http://127.0.0.1:1/nonexistent")
    exit_code = main(["scrape", "--manual"])
    assert exit_code == 1
    err = capsys.readouterr().err
    assert "error" in err.lower() or "錯誤" in err or "失敗" in err
