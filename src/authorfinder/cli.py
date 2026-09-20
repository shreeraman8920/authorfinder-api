"""Command-line entry point: python -m authorfinder or `authorfinder`."""

import argparse
import json
import logging
import sys

from . import __version__
from .crawler import AuthorCrawler
from .export import write_results_xlsx
from .results import dedupe_results

log = logging.getLogger("authorfinder.cli")


def _load_urls_from_file(path: str) -> list[str]:
    """Read URLs from a text file (one per line) or Excel file."""
    import os
    ext = os.path.splitext(path)[1].lower()
    if ext in (".xlsx", ".xls"):
        import openpyxl
        wb = openpyxl.load_workbook(path, read_only=True)
        ws = wb.active
        rows = list(ws.iter_rows(values_only=True))
        wb.close()
        if not rows:
            return []
        header = [str(c).strip().lower() if c else "" for c in rows[0]]
        url_col = 0
        for i, h in enumerate(header):
            if h in ("url", "urls", "article_url", "article url", "link", "article"):
                url_col = i
                break
        urls = []
        for row in rows[1:]:
            if url_col < len(row):
                url = str(row[url_col] or "").strip()
                if url.startswith("http"):
                    urls.append(url)
        return urls
    else:
        urls = []
        with open(path, encoding="utf-8") as f:
            for line in f:
                url = line.strip()
                if url and url.startswith("http"):
                    urls.append(url)
        return urls


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="authorfinder",
        description=(
            "Extract journalist/author contact information from a news article URL. "
            "Fetches the article, locates the author profile page on the same site, "
            "and extracts publicly listed author information."
        ),
    )
    parser.add_argument("urls", nargs="*", help="One or more news article URLs.")
    parser.add_argument("--file", "-f", help="Text file (.txt) or Excel file (.xlsx) with URLs (one per line or first column).")
    parser.add_argument("--no-js", action="store_true", help="Disable Playwright (JavaScript rendering) fallback.")
    parser.add_argument("--timeout", type=float, default=15.0, help="Per-request timeout in seconds (default: 15).")
    parser.add_argument("--delay", type=float, default=1.0, help="Delay between requests in seconds (default: 1).")
    parser.add_argument("--user-agent", default=None, help="Override the crawler's User-Agent string.")
    parser.add_argument("--verbose", "-v", action="store_true", help="Enable debug logging.")
    parser.add_argument("--output", "-o", help="Write JSON output to a file instead of stdout.")
    parser.add_argument(
        "--excel",
        metavar="FILE",
        help="Write the results to an Excel (.xlsx) workbook.",
    )
    parser.add_argument(
        "--dedupe",
        action="store_true",
        help="Merge results that share an author into a single row.",
    )
    parser.add_argument("--version", action="version", version=f"%(prog)s {__version__}")
    return parser


def main(argv=None) -> int:
    args = build_parser().parse_args(argv)
    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="%(asctime)s %(levelname)-7s %(name)s: %(message)s",
        datefmt="%H:%M:%S",
    )

    kwargs = {
        "use_playwright": not args.no_js,
        "timeout": args.timeout,
        "delay": args.delay,
    }
    if args.user_agent:
        kwargs["user_agent"] = args.user_agent

    urls = list(args.urls)
    if args.file:
        urls.extend(_load_urls_from_file(args.file))
    if not urls:
        parser.error("No URLs provided. Pass URLs as arguments or use --file.")

    crawler = AuthorCrawler(**kwargs)
    results = [crawler.crawl(url) for url in urls]
    if args.dedupe:
        before = len(results)
        results = dedupe_results(results)
        log.info("Deduplicated %d results to %d authors", before, len(results))

    payload = results[0] if len(results) == 1 else {"results": results}

    text = json.dumps(payload, indent=2, ensure_ascii=False)
    if args.output:
        with open(args.output, "w", encoding="utf-8") as fh:
            fh.write(text + "\n")
        log.info("Wrote results to %s", args.output)
    else:
        print(text)

    if args.excel:
        try:
            rows = write_results_xlsx(results, args.excel)
        except RuntimeError as exc:
            log.error("%s", exc)
            return 1
        log.info("Wrote %d rows to %s", rows, args.excel)
    return 0


if __name__ == "__main__":
    sys.exit(main())