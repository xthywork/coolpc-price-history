from __future__ import annotations
import argparse
import sys
from coolpc.scraper.run import run_scrape, import_html_file, import_html_dir, ScrapeSkipped


def _print_snapshot(snapshot) -> None:
    print(
        f"[{snapshot.status}] fetched_at={snapshot.fetched_at} "
        f"total={snapshot.total_products} new={snapshot.new_products} "
        f"delisted={snapshot.delisted_products} "
        f"up={snapshot.price_up_count} down={snapshot.price_down_count}"
    )
    if snapshot.status == "failed":
        print(f"錯誤: {snapshot.error_message}", file=sys.stderr)


def cmd_scrape(args: argparse.Namespace) -> int:
    try:
        snapshot = run_scrape(scrape_type="manual" if args.manual else "scheduled")
    except ScrapeSkipped as exc:
        print(f"錯誤: {exc}", file=sys.stderr)
        return 1
    _print_snapshot(snapshot)
    return 0 if snapshot.status == "success" else 1


def cmd_import_html(args: argparse.Namespace) -> int:
    snapshot = import_html_file(args.path)
    _print_snapshot(snapshot)
    return 0 if snapshot.status == "success" else 1


def cmd_import_dir(args: argparse.Namespace) -> int:
    snapshots = import_html_dir(args.path)
    for snapshot in snapshots:
        _print_snapshot(snapshot)
    return 0 if all(s.status == "success" for s in snapshots) else 1


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="coolpc-scraper")
    sub = parser.add_subparsers(dest="command", required=True)

    p_scrape = sub.add_parser("scrape", help="執行一次抓取")
    p_scrape.add_argument("--manual", action="store_true", help="標記為手動抓取")
    p_scrape.set_defaults(func=cmd_scrape)

    p_import = sub.add_parser("import-html", help="匯入單一 HTML 檔案")
    p_import.add_argument("path")
    p_import.set_defaults(func=cmd_import_html)

    p_import_dir = sub.add_parser("import-dir", help="匯入整個目錄的 HTML")
    p_import_dir.add_argument("path")
    p_import_dir.set_defaults(func=cmd_import_dir)

    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
