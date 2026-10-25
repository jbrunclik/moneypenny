"""Does a Dependabot PR contain a major version update? (P3)

Reads the PR title and body (stdin, or the PR_TEXT environment variable) and
exits 0 when any listed update is major, 1 when all are patch or minor. A
0.x -> 0.y bump counts as major (semver: anything may break before 1.0).
Text without any recognisable "from X to Y" counts as major, so a person
looks at it.
"""

import os
import re
import sys

_UPDATE = re.compile(r"from `?v?(\d+)(?:\.(\d+))?[^\s`]*`? to `?v?(\d+)(?:\.(\d+))?")


def _is_major(old_major: str, old_minor: str, new_major: str, new_minor: str) -> bool:
    if old_major != new_major:
        return True
    return old_major == "0" and (old_minor or "0") != (new_minor or "0")


def has_major_update(text: str) -> bool:
    updates = _UPDATE.findall(text)
    return not updates or any(_is_major(*update) for update in updates)


if __name__ == "__main__":
    text = os.environ.get("PR_TEXT") or sys.stdin.read()
    sys.exit(0 if has_major_update(text) else 1)
