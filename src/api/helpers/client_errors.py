"""Browser error reports: cut to size, then fingerprint.

The message and stack can quote what was on screen, so both are kept short:
enough to find the bug, not to read along. The fingerprint ignores what a
rebuild changes (asset hashes, line and column numbers), so one bug stays one
row across deploys.
"""

import hashlib
import re

from src.api.schemas.client_errors import ClientErrorReport
from src.db.models import db

MESSAGE_MAX_CHARS = 300
STACK_MAX_CHARS = 2000
PATH_MAX_CHARS = 200
USER_AGENT_MAX_CHARS = 200

_ASSET_HASH = re.compile(r"-[A-Za-z0-9_-]{8}(\.js)")
_NUMBERS = re.compile(r"\d+")


def _first_frame(stack: str | None, message: str) -> str:
    for line in (stack or "").splitlines():
        line = line.strip()
        if line and message not in line:
            return line
    return ""


def fingerprint(kind: str, message: str, stack: str | None) -> str:
    frame = _ASSET_HASH.sub(r"\1", _first_frame(stack, message))
    key = "|".join([kind, _NUMBERS.sub("#", message), _NUMBERS.sub("#", frame)])
    return hashlib.sha256(key.encode()).hexdigest()


def record_report(user_id: str, report: ClientErrorReport, user_agent: str | None) -> None:
    message = report.message[:MESSAGE_MAX_CHARS]
    stack = report.stack[:STACK_MAX_CHARS] if report.stack else None
    path = report.path.split("?")[0].split("#")[0][:PATH_MAX_CHARS] if report.path else None
    db.record_client_error(
        user_id,
        fingerprint(report.kind.value, report.message, report.stack),
        report.kind.value,
        message,
        stack,
        path,
        report.app_version,
        user_agent[:USER_AGENT_MAX_CHARS] if user_agent else None,
    )
