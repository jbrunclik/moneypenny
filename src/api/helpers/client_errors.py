"""Browser error reports: cut to size, then fingerprint.

The message and stack can quote what was on screen, so both are kept short:
enough to find the bug, not to read along. The fingerprint ignores what a
rebuild changes (asset hashes, line and column numbers), so one bug stays one
row across deploys.

Layout reports are the opposite: the point is to see whether a build
regressed, so their fingerprint includes the build (version and [kbN]
marker), and their measurements go into the detail column as JSON.
"""

import hashlib
import json
import re

from src.api.schemas.client_errors import ClientErrorKind, ClientErrorReport, LayoutCheckDetail
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


def _cut_path(path: str | None) -> str | None:
    return path.split("?")[0].split("#")[0][:PATH_MAX_CHARS] if path else None


def fingerprint(kind: str, message: str, stack: str | None) -> str:
    frame = _ASSET_HASH.sub(r"\1", _first_frame(stack, message))
    key = "|".join([kind, _NUMBERS.sub("#", message), _NUMBERS.sub("#", frame)])
    return hashlib.sha256(key.encode()).hexdigest()


def _layout_fingerprint(app_version: str | None, layout: LayoutCheckDetail) -> str:
    key = "|".join(
        [
            ClientErrorKind.LAYOUT.value,
            layout.invariant.value,
            layout.shape,
            app_version or "",
            layout.build_marker,
            "standalone" if layout.standalone else "tab",
        ]
    )
    return hashlib.sha256(key.encode()).hexdigest()


def _layout_detail(layout: LayoutCheckDetail) -> str:
    measurements = {name: round(value, 1) for name, value in layout.measurements.items()}
    return json.dumps(
        {
            "invariant": layout.invariant.value,
            "shape": layout.shape,
            "build_marker": layout.build_marker,
            "standalone": layout.standalone,
            "ios_version": layout.ios_version,
            "measurements": measurements,
        },
        separators=(",", ":"),
    )


def record_report(user_id: str, report: ClientErrorReport, user_agent: str | None) -> None:
    if report.layout is not None:
        _record_layout_report(user_id, report, report.layout, user_agent)
        return
    message = report.message[:MESSAGE_MAX_CHARS]
    stack = report.stack[:STACK_MAX_CHARS] if report.stack else None
    path = _cut_path(report.path)
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


def _record_layout_report(
    user_id: str, report: ClientErrorReport, layout: LayoutCheckDetail, user_agent: str | None
) -> None:
    db.record_client_error(
        user_id,
        _layout_fingerprint(report.app_version, layout),
        ClientErrorKind.LAYOUT.value,
        f"{layout.invariant.value}: {layout.shape}",
        None,
        _cut_path(report.path),
        report.app_version,
        user_agent[:USER_AGENT_MAX_CHARS] if user_agent else None,
        detail=_layout_detail(layout),
    )
