from coolpc.cli import main
from coolpc.db.session import get_engine
from coolpc.db.models import Base

SAMPLE = "/home/xthybot/coolpc/download/2026-02-01-21-40.html"


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
