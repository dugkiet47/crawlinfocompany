#!/usr/bin/env python3
"""
MaSoThue.com Crawler
Crawl Vietnamese company tax data from masothue.com

Usage:
    python crawl.py search "0319485630"          # Search by Tax ID
    python crawl.py search "Minh Huy"             # Search by company name
    python crawl.py all                            # Crawl ALL companies (all provinces)
    python crawl.py all --province "Ho Chi Minh"   # Crawl one province only
    python crawl.py all --max-pages 5              # Limit pages per province

Options:
    --format csv|excel|both    Output format (default: both)
    --detail                   Fetch full detail for each company (slower)
    --delay 1.5                Delay between requests in seconds
    --max-pages N              Max pages to crawl per province
    --province NAME            Filter to a specific province (partial match)
"""

import argparse
import sys
from scraper import MasoThueScraper, SourceBlockedError, DataMismatchError
import requests
from exporter import export_csv, export_excel


def cmd_search(args):
    scraper = MasoThueScraper(delay=args.delay)
    query = " ".join(args.query)
    print(f"Searching: {query}")

    results = scraper.search(query)
    if not results:
        print("No results found.")
        return

    print(f"Found {len(results)} result(s) from search.\n")

    # If --detail flag, fetch full details for each
    if args.detail:
        detailed = []
        for i, r in enumerate(results):
            url = r.get("detail_url")
            if url:
                print(f"  [{i+1}/{len(results)}] Fetching detail: {r.get('company_name', url)}")
                detail = scraper.get_company_detail(url, expected_tax_id=r.get("tax_id"))
                if detail:
                    detail["detail_url"] = url
                    detailed.append(detail)
                else:
                    detailed.append(r)
            else:
                detailed.append(r)
        results = detailed
    else:
        # If single result from direct search, it already has details
        pass

    _print_summary(results)
    _export(results, args.format)


def cmd_all(args):
    scraper = MasoThueScraper(delay=args.delay)
    print("Fetching province list...")
    provinces = scraper.get_provinces()
    if not provinces:
        print("ERROR: Could not fetch provinces list.")
        sys.exit(1)

    print(f"Found {len(provinces)} provinces.\n")

    # Filter province if specified (supports ASCII matching via URL slug)
    if args.province:
        keyword = args.province.lower()
        provinces = [(n, u) for n, u in provinces
                     if keyword in n.lower() or keyword in u.lower()]
        if not provinces:
            print(f"No province matching '{args.province}'.")
            sys.exit(1)
        print(f"Filtered to {len(provinces)} province(s): {', '.join(n for n, _ in provinces)}\n")

    all_companies = []
    for prov_name, prov_url in provinces:
        print(f"\n=== {prov_name} ===")
        count = 0
        for company in scraper.crawl_province(prov_url, max_pages=args.max_pages):
            if args.detail and company.get("detail_url"):
                detail = scraper.get_company_detail(company["detail_url"], expected_tax_id=company.get("tax_id"))
                if detail:
                    detail["detail_url"] = company["detail_url"]
                    company = detail
            all_companies.append(company)
            count += 1
            if args.max_records and len(all_companies) >= args.max_records:
                break
        print(f"  => {count} companies from {prov_name}")

        # Save intermediate results every 1000 records
        if len(all_companies) % 1000 < 20 and len(all_companies) > 0:
            print(f"  [Checkpoint] {len(all_companies)} total companies so far...")
        if args.max_records and len(all_companies) >= args.max_records:
            break

    print(f"\n{'='*50}")
    print(f"Total: {len(all_companies)} companies")
    _export(all_companies, args.format)


def _print_summary(results):
    print(f"\n{'='*60}")
    for r in results[:10]:
        print(f"  MST: {r.get('tax_id', 'N/A'):15s} | {r.get('company_name', 'N/A')}")
        if r.get("representative"):
            print(f"  {'':15s}   Rep: {r['representative']}")
        if r.get("address") or r.get("tax_address"):
            print(f"  {'':15s}   Addr: {r.get('tax_address') or r.get('address')}")
        if r.get("status"):
            print(f"  {'':15s}   Status: {r['status']}")
        print()
    if len(results) > 10:
        print(f"  ... and {len(results)-10} more")
    print(f"{'='*60}")


def _export(companies, fmt):
    if not companies:
        return
    if fmt in ("csv", "both"):
        export_csv(companies)
    if fmt in ("excel", "both"):
        export_excel(companies)


def main():
    parser = argparse.ArgumentParser(
        description="Crawl company data from masothue.com",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__,
    )
    # Common args on parent parser
    common = argparse.ArgumentParser(add_help=False)
    common.add_argument("--format", choices=["csv", "excel", "both"], default="both",
                        help="Output format (default: both)")
    common.add_argument("--detail", action="store_true",
                        help="Fetch full detail page for every company (slower)")
    common.add_argument("--delay", type=float, default=1.0,
                        help="Delay between requests in seconds (default: 1.0)")

    sub = parser.add_subparsers(dest="command")

    # search sub-command
    p_search = sub.add_parser("search", parents=[common], help="Search by Tax ID or company name")
    p_search.add_argument("query", nargs="+", help="Tax ID or company name to search")

    # all sub-command
    p_all = sub.add_parser("all", parents=[common], help="Crawl all companies")
    p_all.add_argument("--province", type=str, default=None,
                       help="Filter to province (partial name match)")
    p_all.add_argument("--max-pages", type=int, default=None,
                       help="Max pages per province")

    p_all.add_argument("--max-records", type=int, default=None,
                       help="Stop after this many records total (use for bounded trials)")

    args = parser.parse_args()
    if getattr(args, "delay", 0) < 0:
        parser.error("--delay must be non-negative")
    for option in ("max_pages", "max_records"):
        value = getattr(args, option, None)
        if value is not None and value < 1:
            parser.error("--" + option.replace("_", "-") + " must be positive")

    if not args.command:
        parser.print_help()
        sys.exit(1)

    try:
        if args.command == "search":
            cmd_search(args)
        elif args.command == "all":
            cmd_all(args)
    except (SourceBlockedError, DataMismatchError, requests.RequestException, ValueError) as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
