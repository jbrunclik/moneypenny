"""Every script a systemd timer runs sets up logging.

Nov 17 2026: the backup, defrag, vacuum and currency scripts used get_logger
without setup_logging(), so Python's fallback handler dropped their INFO lines
("Backup compressed", "Memories expired", ...) - the re-measures that read
them found nothing in the journal. The scheduler builds the app, which does it.
"""

import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
_SCRIPT = re.compile(r"python (scripts/\w+\.py)")


def _timer_scripts() -> list[Path]:
    scripts = set()
    for unit in (ROOT / "systemd").glob("*.service"):
        scripts.update(_SCRIPT.findall(unit.read_text()))
    return sorted(ROOT / s for s in scripts)


def test_the_timer_scripts_are_found() -> None:
    names = {p.name for p in _timer_scripts()}
    assert {"backup_databases.py", "defragment_memories.py", "run_agent_scheduler.py"} <= names


def test_every_timer_script_sets_up_logging() -> None:
    silent = [
        p.name
        for p in _timer_scripts()
        if "setup_logging()" not in (text := p.read_text()) and "create_app(" not in text
    ]
    assert silent == []
