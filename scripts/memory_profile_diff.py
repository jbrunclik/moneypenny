#!/usr/bin/env python3
"""Show what grew between two tracemalloc snapshots of the same worker.

Snapshots come from a worker running with MEMORY_PROFILE_ENABLED=true:
`kill -USR2 <worker pid>` writes one to MEMORY_PROFILE_DIR.

Usage:
    python scripts/memory_profile_diff.py OLD.tracemalloc NEW.tracemalloc
    python scripts/memory_profile_diff.py OLD NEW --group-by traceback --limit 10
"""

import argparse
import sys
from pathlib import Path

# Add parent directory to path so we can import from src
sys.path.insert(0, str(Path(__file__).parent.parent))

from src.utils.memory_profile import top_growth


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("old", type=Path)
    parser.add_argument("new", type=Path)
    parser.add_argument("--group-by", choices=("lineno", "filename", "traceback"), default="lineno")
    parser.add_argument("--limit", type=int, default=25)
    args = parser.parse_args()
    print("\n".join(top_growth(args.old, args.new, group_by=args.group_by, limit=args.limit)))
    return 0


if __name__ == "__main__":
    sys.exit(main())
