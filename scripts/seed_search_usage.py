#!/usr/bin/env python3
"""Seed or inspect the monthly search-usage counters.

The search provider router (src/utils/search_provider.py) bills each metered
search to a kv_store counter. Use this to backfill usage already consumed on
a provider's dashboard (e.g. after switching to the router mid-month), or to
check where the month stands.

Usage:
    python scripts/seed_search_usage.py                     # show current usage
    python scripts/seed_search_usage.py brave 812           # set brave usage
    python scripts/seed_search_usage.py brave 812 --month 2026-08
"""

import argparse
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from dotenv import load_dotenv

load_dotenv(Path(__file__).parent.parent / ".env")

from src.db.models import db  # noqa: E402
from src.utils.search_provider import (  # noqa: E402
    _PROVIDERS,
    _SYSTEM_USER_ID,
    USAGE_NAMESPACE,
    get_monthly_usage,
    usage_key,
)


def show_usage() -> None:
    print(f"{'provider':<10} {'used':>6}  quota")
    for provider in _PROVIDERS:
        quota = provider.monthly_quota()
        used = get_monthly_usage(provider.name) if quota is not None else "-"
        configured = "" if quota is None or provider.api_key() else "  (no API key)"
        print(
            f"{provider.name:<10} {used!s:>6}  {quota if quota is not None else 'unmetered'}{configured}"
        )


def seed(provider: str, count: int, month: str | None) -> None:
    names = {p.name for p in _PROVIDERS if p.monthly_quota() is not None}
    if provider not in names:
        sys.exit(f"Unknown metered provider {provider!r} (choose from: {', '.join(sorted(names))})")
    key = f"{provider}:{month}" if month else usage_key(provider)
    db.kv_set(_SYSTEM_USER_ID, USAGE_NAMESPACE, key, str(count))
    print(f"Set {key} = {count}")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("provider", nargs="?", help="Provider name (brave, tavily, exa)")
    parser.add_argument("count", nargs="?", type=int, help="Searches already used this month")
    parser.add_argument("--month", help="Month key YYYY-MM (default: current month)")
    args = parser.parse_args()

    if args.month and not re.fullmatch(r"\d{4}-\d{2}", args.month):
        sys.exit("--month must be YYYY-MM")

    if args.provider is None:
        show_usage()
        return
    if args.count is None:
        sys.exit("Provide the used-search count, e.g.: seed_search_usage.py brave 812")
    seed(args.provider, args.count, args.month)


if __name__ == "__main__":
    main()
