#!/usr/bin/env python3
"""Cost analysis: where the money goes, from message_costs + metadata.

Reads the SQLite DB directly (stdlib only, safe to run on prod):

    python scripts/analyze_costs.py [days] [db_path]

Sections: totals, by conversation type, by model, web-search correlation
(messages with cited sources vs without), input-token distribution,
top messages/conversations, daily trend.
"""

from __future__ import annotations

import sqlite3
import sys
from datetime import datetime, timedelta
from pathlib import Path


def _conv_type_case() -> str:
    return """
        CASE
            WHEN c.agent_id IS NOT NULL THEN 'agent'
            WHEN c.is_planning = 1 THEN 'planner'
            WHEN c.is_sports = 1 THEN 'sports'
            WHEN c.is_language = 1 THEN 'language'
            ELSE 'chat'
        END
    """


def _fmt_usd(value: float) -> str:
    return f"${value:,.2f}"


def _pct(part: float, whole: float) -> str:
    return f"{(part / whole * 100):5.1f}%" if whole else "  0.0%"


def _percentile(sorted_values: list[int], pct: float) -> int:
    if not sorted_values:
        return 0
    index = min(int(len(sorted_values) * pct), len(sorted_values) - 1)
    return sorted_values[index]


def main() -> None:
    days = int(sys.argv[1]) if len(sys.argv) > 1 else 30
    db_path = sys.argv[2] if len(sys.argv) > 2 else "chatbot.db"
    if not Path(db_path).exists():
        sys.exit(f"DB not found: {db_path}")

    since = (datetime.now() - timedelta(days=days)).isoformat()
    conn = sqlite3.connect(f"file:{db_path}?mode=ro", uri=True)
    conn.row_factory = sqlite3.Row
    conv_type = _conv_type_case()

    print(f"=== Cost analysis: last {days} days (since {since[:10]}) ===\n")

    # ---- Totals
    total = conn.execute(
        """SELECT COUNT(*) n, COALESCE(SUM(cost_usd),0) usd,
                  COALESCE(SUM(input_tokens),0) tin, COALESCE(SUM(output_tokens),0) tout,
                  COALESCE(SUM(image_generation_cost_usd),0) img
           FROM message_costs WHERE created_at >= ?""",
        (since,),
    ).fetchone()
    if not total["n"]:
        sys.exit("No cost rows in window.")
    print(
        f"TOTAL: {_fmt_usd(total['usd'])} over {total['n']} messages "
        f"(avg {_fmt_usd(total['usd'] / total['n'])}/msg)\n"
        f"  input tokens:  {total['tin']:>12,}  ({total['tin'] / total['n']:>9,.0f}/msg)\n"
        f"  output tokens: {total['tout']:>12,}  ({total['tout'] / total['n']:>9,.0f}/msg)\n"
        f"  input:output ratio: {total['tin'] / max(total['tout'], 1):.1f}:1\n"
        f"  image generation:   {_fmt_usd(total['img'])}\n"
    )

    # ---- By conversation type
    print("BY CONVERSATION TYPE:")
    rows = conn.execute(
        f"""SELECT CASE WHEN c.id IS NULL THEN 'deleted' ELSE {conv_type} END ctype,
                   COUNT(*) n, SUM(mc.cost_usd) usd,
                   SUM(mc.input_tokens) tin, AVG(mc.input_tokens) avg_in
            FROM message_costs mc LEFT JOIN conversations c ON mc.conversation_id = c.id
            WHERE mc.created_at >= ? GROUP BY ctype ORDER BY usd DESC""",
        (since,),
    ).fetchall()
    for r in rows:
        print(
            f"  {r['ctype']:<9} {_fmt_usd(r['usd']):>9} {_pct(r['usd'], total['usd'])} "
            f"| {r['n']:>5} msgs | avg in {r['avg_in']:>9,.0f} tok"
        )
    print()

    # ---- By model
    print("BY MODEL:")
    for r in conn.execute(
        """SELECT model, COUNT(*) n, SUM(cost_usd) usd FROM message_costs
           WHERE created_at >= ? GROUP BY model ORDER BY usd DESC""",
        (since,),
    ):
        print(
            f"  {r['model']:<28} {_fmt_usd(r['usd']):>9} {_pct(r['usd'], total['usd'])} | {r['n']:>5} msgs"
        )
    print()

    # ---- Web search correlation (cited sources as the marker)
    print("WEB SEARCH CORRELATION (messages with cited sources vs without):")
    for r in conn.execute(
        """SELECT CASE WHEN m.id IS NULL THEN 'deleted msg'
                       WHEN m.sources IS NOT NULL AND m.sources != '[]' THEN 'with sources'
                       ELSE 'no sources' END grp,
                  COUNT(*) n, SUM(mc.cost_usd) usd, AVG(mc.cost_usd) avg_usd,
                  AVG(mc.input_tokens) avg_in, AVG(mc.output_tokens) avg_out
           FROM message_costs mc LEFT JOIN messages m ON mc.message_id = m.id
           WHERE mc.created_at >= ? GROUP BY grp ORDER BY usd DESC""",
        (since,),
    ):
        print(
            f"  {r['grp']:<13} {_fmt_usd(r['usd']):>9} {_pct(r['usd'], total['usd'])} "
            f"| {r['n']:>5} msgs | avg {_fmt_usd(r['avg_usd'])} "
            f"| avg in {r['avg_in']:>9,.0f} | avg out {r['avg_out']:>6,.0f}"
        )
    print()

    # ---- Input token distribution per type (context bloat finder)
    print("INPUT TOKEN DISTRIBUTION (p50 / p90 / max):")
    by_type: dict[str, list[int]] = {}
    for r in conn.execute(
        f"""SELECT {conv_type} ctype, mc.input_tokens tin
            FROM message_costs mc JOIN conversations c ON mc.conversation_id = c.id
            WHERE mc.created_at >= ?""",
        (since,),
    ):
        by_type.setdefault(r["ctype"], []).append(r["tin"])
    for ctype, values in sorted(by_type.items(), key=lambda kv: -sum(kv[1])):
        values.sort()
        print(
            f"  {ctype:<9} p50 {_percentile(values, 0.5):>9,} | "
            f"p90 {_percentile(values, 0.9):>9,} | max {values[-1]:>9,}"
        )
    print()

    # ---- Top messages
    print("TOP 10 MOST EXPENSIVE MESSAGES:")
    for r in conn.execute(
        f"""SELECT mc.created_at, mc.cost_usd, mc.input_tokens, mc.output_tokens,
                   {conv_type} ctype, c.title,
                   (m.sources IS NOT NULL AND m.sources != '[]') has_sources
            FROM message_costs mc
            JOIN conversations c ON mc.conversation_id = c.id
            LEFT JOIN messages m ON mc.message_id = m.id
            WHERE mc.created_at >= ? ORDER BY mc.cost_usd DESC LIMIT 10""",
        (since,),
    ):
        marker = " [web]" if r["has_sources"] else ""
        print(
            f"  {r['created_at'][:16]} {_fmt_usd(r['cost_usd']):>7} "
            f"| in {r['input_tokens']:>8,} out {r['output_tokens']:>6,} "
            f"| {r['ctype']:<8}{marker} | {(r['title'] or '')[:38]}"
        )
    print()

    # ---- Top conversations
    print("TOP 10 MOST EXPENSIVE CONVERSATIONS:")
    for r in conn.execute(
        f"""SELECT c.title, {conv_type} ctype, COUNT(*) n, SUM(mc.cost_usd) usd,
                   SUM(mc.input_tokens) tin
            FROM message_costs mc JOIN conversations c ON mc.conversation_id = c.id
            WHERE mc.created_at >= ?
            GROUP BY c.id ORDER BY usd DESC LIMIT 10""",
        (since,),
    ):
        print(
            f"  {_fmt_usd(r['usd']):>8} {_pct(r['usd'], total['usd'])} | {r['n']:>4} msgs "
            f"| in {r['tin']:>10,} | {r['ctype']:<8} | {(r['title'] or '')[:38]}"
        )
    print()

    # ---- Daily trend
    print("DAILY TREND (last 14 days):")
    for r in conn.execute(
        """SELECT substr(created_at, 1, 10) day, COUNT(*) n, SUM(cost_usd) usd
           FROM message_costs WHERE created_at >= ?
           GROUP BY day ORDER BY day DESC LIMIT 14""",
        ((datetime.now() - timedelta(days=14)).isoformat(),),
    ):
        bar = "#" * min(int(r["usd"] * 20), 60)
        print(f"  {r['day']}  {_fmt_usd(r['usd']):>8} | {r['n']:>4} msgs | {bar}")

    conn.close()


if __name__ == "__main__":
    main()
