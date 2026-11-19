#!/usr/bin/env python3
"""Freeze a shared chat's compaction summary into its fixture.

Shared chats (evals/chats.py) carry the summary production would send for
their older turns. It is generated ONCE with the real summarizer - the
messages older than CONVERSATION_COMPACTION_KEEP_RECENT - then reviewed and
committed, so every eval run sees the same context and pays nothing for it.

Hits the live API (~$0.01-0.03 a chat). Read the summary after it is
written: a wrong fact in it is a wrong fact in every case on that chat.

Usage:
    PYTHONPATH=. python evals/freeze_summary.py cycling_program [more names...]
"""

import sys
from pathlib import Path
from typing import Any

import yaml

from evals.chats import CHATS_DIR


def freeze_summary(path: Path, summarize: Any = None) -> str:
    """Summarize the chat's older messages and store the text as ``summary``."""
    from src.agent.compaction_segments import extend_segments, render_segments
    from src.config import Config

    text = path.read_text()
    # The header comment (what the chat is, that it is synthetic) survives the rewrite
    header = "".join(line for line in text.splitlines(keepends=True) if line.startswith("#"))
    header = header if text.startswith("#") else ""
    data = yaml.safe_load(text)
    messages = data.get("messages") or []
    older = messages[: max(0, len(messages) - Config.CONVERSATION_COMPACTION_KEEP_RECENT)]
    if not older:
        raise ValueError(f"{path.name}: too short to summarize ({len(messages)} messages)")
    segments = extend_segments([], older, 0, len(older), summarize=summarize)
    if not segments:
        raise RuntimeError(f"{path.name}: the summarizer failed")
    summary = render_segments(segments)
    data["summary"] = summary
    data["summary_covers"] = len(older)  # the chat messages the summary stands for
    path.write_text(header + yaml.safe_dump(data, allow_unicode=True, sort_keys=False, width=100))
    return summary


def main() -> int:
    from evals.run import isolate_environment

    isolate_environment()
    for name in sys.argv[1:]:
        summary = freeze_summary(CHATS_DIR / f"{name}.yaml")
        print(f"{name}: {len(summary)} characters\n{summary}\n")
    return 0


if __name__ == "__main__":
    sys.exit(main())
