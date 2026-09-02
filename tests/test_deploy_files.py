import configparser
from pathlib import Path

DEPLOY_DIR = Path(__file__).parent.parent / "deploy"


def _parse(filename: str) -> configparser.ConfigParser:
    cfg = configparser.ConfigParser(strict=False)
    cfg.read(DEPLOY_DIR / filename, encoding="utf-8")
    return cfg


def test_scraper_service_is_oneshot_and_calls_scrape():
    cfg = _parse("coolpc-scraper.service")
    assert cfg["Service"]["Type"] == "oneshot"
    assert "coolpc-scraper scrape" in cfg["Service"]["ExecStart"]


def test_scraper_timer_runs_every_6_hours_and_survives_reboot():
    cfg = _parse("coolpc-scraper.timer")
    assert cfg["Timer"]["OnCalendar"] == "*-*-* 0/6:00:00"
    assert cfg["Timer"]["Persistent"] == "true"
    assert cfg["Install"]["WantedBy"] == "timers.target"


def test_public_service_listens_on_33690():
    cfg = _parse("coolpc-public.service")
    assert "0.0.0.0" in cfg["Service"]["ExecStart"]
    assert "33690" in cfg["Service"]["ExecStart"]
    assert "coolpc.public_api.app:app" in cfg["Service"]["ExecStart"]
    assert cfg["Install"]["WantedBy"] == "multi-user.target"


def test_admin_service_listens_on_33691():
    cfg = _parse("coolpc-admin.service")
    assert "0.0.0.0" in cfg["Service"]["ExecStart"]
    assert "33691" in cfg["Service"]["ExecStart"]
    assert "coolpc.admin_api.app:app" in cfg["Service"]["ExecStart"]
    assert cfg["Install"]["WantedBy"] == "multi-user.target"
