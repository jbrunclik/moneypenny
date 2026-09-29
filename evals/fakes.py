"""In-memory fake integration backends for eval cases.

Evals run without integration credentials, so the tools most prone to
failure (Sep 2026: Todoist errored in 36% of the turns using it, Garmin 14%)
had no coverage. A case opts in with ``integrations:``; the fake replaces the
tool's HTTP/client seam (not the tool), so the real tool code - argument
handling, formatting, error envelopes, not-connected messaging - is what the
agent exercises.

Fixture shape (YAML):

    integrations:
      todoist:
        projects: [{id: p1, name: Work}]
        sections: [{id: s1, project_id: p1, name: Active}]
        tasks: [{id: t1, content: "...", project_id: p1, due: {date: 2026-09-30}}]
      garmin:
        state: connected          # or: disconnected (expired) / not_connected
        data: {get_hrv_data: {...}, get_training_readiness: [...], ...}

``actions`` on each fake records every mutating call, shown to the judge.
"""

from __future__ import annotations

import contextlib
import copy
import re
from collections.abc import Iterator
from datetime import date, timedelta
from typing import Any
from unittest.mock import patch

# Mirrors the real API's rejection of a malformed filter (error_code 55)
_INVALID_FILTER_ERROR = (
    'Todoist API error (400): {"error":"The search query is incorrect",'
    '"error_code":55,"error_tag":"INVALID_SEARCH_QUERY","http_code":400}'
)

_ATOM_PATTERNS = [
    r"today",
    r"tomorrow",
    r"overdue",
    r"no (due )?date",
    r"(next )?\d+ days",
    r"p[1-4]",
    r"#[^&|!()]+",
    r"@[^&|!()\s]+",
    r"search:\s*.+",
    r"assigned to:\s*.+",
    r"(due )?(before|after):\s*.+",
    r"\d{4}-\d{2}-\d{2}",
    r"recurring",
    r"no labels",
]


class FakeTodoist:
    """Just enough of the Todoist REST/Sync API for the tool's actions."""

    def __init__(self, fixture: dict[str, Any]) -> None:
        self.projects: list[dict[str, Any]] = copy.deepcopy(fixture.get("projects") or [])
        self.sections: list[dict[str, Any]] = copy.deepcopy(fixture.get("sections") or [])
        self.tasks: list[dict[str, Any]] = copy.deepcopy(fixture.get("tasks") or [])
        for task in self.tasks:
            task.setdefault("checked", False)
            task.setdefault("priority", 1)
            task.setdefault("labels", [])
            task.setdefault("description", "")
            for key in ("section_id", "parent_id", "responsible_uid", "due"):
                task.setdefault(key, None)
            if isinstance(task["due"], dict):
                task["due"]["date"] = str(task["due"].get("date"))
        self.actions: list[str] = []
        self._next = 1000

    # -- filter language -------------------------------------------------
    def _atom_ok(self, atom: str) -> bool:
        atom = atom.strip().strip("()").strip()
        return any(re.fullmatch(p, atom, re.IGNORECASE) for p in _ATOM_PATTERNS)

    def _validate(self, query: str) -> None:
        atoms = [a for a in re.split(r"[&|]", query.replace("!", "")) if a.strip()]
        if not atoms or not all(self._atom_ok(a) for a in atoms):
            raise Exception(_INVALID_FILTER_ERROR)

    def _matches_atom(self, task: dict[str, Any], atom: str) -> bool:
        atom = atom.strip().strip("()").strip().lower()
        negate = atom.startswith("!")
        atom = atom.lstrip("!").strip()
        due = (task.get("due") or {}).get("date")
        today = date.today()
        due_d = date.fromisoformat(due[:10]) if due else None
        result: bool
        if atom == "today":
            result = due_d == today
        elif atom == "tomorrow":
            result = due_d == today + timedelta(days=1)
        elif atom == "overdue":
            result = bool(due_d and due_d < today)
        elif re.fullmatch(r"no (due )?date", atom):
            result = due_d is None
        elif m := re.fullmatch(r"(?:next )?(\d+) days", atom):
            result = bool(due_d and today <= due_d <= today + timedelta(days=int(m.group(1))))
        elif m := re.fullmatch(r"p([1-4])", atom):
            # Filter p1 = API priority 4 (Todoist inverts them)
            result = task.get("priority") == 5 - int(m.group(1))
        elif atom.startswith("#"):
            name = atom[1:].strip()
            project = next((p for p in self.projects if p["id"] == task.get("project_id")), None)
            result = bool(project and project["name"].lower() == name)
        elif atom.startswith("@"):
            result = atom[1:] in [label.lower() for label in task.get("labels") or []]
        elif atom.startswith("search:"):
            result = atom.split(":", 1)[1].strip() in task["content"].lower()
        else:
            result = True  # accepted but not modeled
        return result != negate

    def _filter(self, query: str) -> list[dict[str, Any]]:
        self._validate(query)
        open_tasks = [t for t in self.tasks if not t.get("checked")]
        return [
            t
            for t in open_tasks
            if any(
                all(self._matches_atom(t, a) for a in part.split("&") if a.strip())
                for part in query.split("|")
            )
        ]

    # -- API seams -------------------------------------------------------
    def _new_id(self, prefix: str) -> str:
        self._next += 1
        return f"{prefix}{self._next}"

    def _find(self, items: list[dict[str, Any]], item_id: str) -> dict[str, Any]:
        for item in items:
            if item["id"] == item_id:
                return item
        raise Exception(
            'Todoist API error (404): {"error":"Task not found","error_tag":"NOT_FOUND"}'
        )

    def api_request(
        self,
        method: str,
        endpoint: str,
        token: str,
        data: dict[str, Any] | None = None,
        params: dict[str, Any] | None = None,
    ) -> Any:
        data = data or {}
        params = params or {}
        parts = endpoint.strip("/").split("/")
        kind = parts[0]
        store = {"tasks": self.tasks, "projects": self.projects, "sections": self.sections}[kind]
        if method == "GET":
            if endpoint == "/tasks/filter":
                return copy.deepcopy(self._filter(params.get("query", "")))
            if len(parts) == 1:
                items = [t for t in store if not t.get("checked")]
                if params.get("project_id"):
                    items = [t for t in items if t.get("project_id") == params["project_id"]]
                return copy.deepcopy(items)
            if len(parts) == 3 and parts[2] == "collaborators":
                return []
            return copy.deepcopy(self._find(store, parts[1]))
        if method == "POST":
            if len(parts) == 1:
                item: dict[str, Any] = {"id": self._new_id(kind[0]), **data}
                if kind == "tasks":
                    due = data.get("due_date") or data.get("due_string")
                    item.update(
                        {
                            "checked": False,
                            "priority": data.get("priority", 1),
                            "labels": data.get("labels") or [],
                            "due": {"date": str(due), "string": str(due)} if due else None,
                            "section_id": data.get("section_id"),
                            "parent_id": None,
                            "responsible_uid": None,
                        }
                    )
                store.append(item)
                self.actions.append(
                    f"created {kind[:-1]} {item.get('content') or item.get('name')!r} {data}"
                )
                return copy.deepcopy(item)
            target = self._find(store, parts[1])
            if len(parts) == 3 and parts[2] == "close":
                target["checked"] = True
                self.actions.append(f"completed task {target['content']!r}")
                return None
            if len(parts) == 3 and parts[2] == "reopen":
                target["checked"] = False
                self.actions.append(f"reopened task {target['content']!r}")
                return None
            target.update(data)
            self.actions.append(f"updated {kind[:-1]} {parts[1]} {data}")
            return copy.deepcopy(target)
        if method == "DELETE":
            target = self._find(store, parts[1])
            store.remove(target)
            self.actions.append(
                f"deleted {kind[:-1]} {target.get('content') or target.get('name')!r}"
            )
            return None
        raise ValueError(f"unsupported {method} {endpoint}")

    def sync_request(self, token: str, commands: list[dict[str, Any]]) -> dict[str, Any]:
        for cmd in commands:
            self.actions.append(f"sync {cmd.get('type')} {cmd.get('args')}")
        return {"sync_status": {cmd.get("uuid", ""): "ok" for cmd in commands}}


class FakeGarmin:
    """Garmin client whose API methods return fixture data by method name."""

    def __init__(self, data: dict[str, Any]) -> None:
        self._data = data
        self.calls: list[str] = []
        # Read-only fake: no mutations to report (also keeps __getattr__
        # from answering `actions` with an API-method stub)
        self.actions: list[str] = []

    def __getattr__(self, name: str) -> Any:
        if name.startswith("_"):
            raise AttributeError(name)

        def call(*args: Any, **kwargs: Any) -> Any:
            self.calls.append(name)
            if name not in self._data:
                raise Exception(f"no data for {name}")
            return copy.deepcopy(self._data[name])

        return call


@contextlib.contextmanager
def fake_integrations(spec: dict[str, Any]) -> Iterator[dict[str, Any]]:
    """Install the fakes a case asks for; yields {name: fake} for reporting."""
    fakes: dict[str, Any] = {}
    with contextlib.ExitStack() as stack:
        if "todoist" in spec:
            todo = FakeTodoist(spec["todoist"] or {})
            fakes["todoist"] = todo
            stack.enter_context(
                patch("src.agent.tools.todoist_client.get_todoist_token", lambda: "fake")
            )
            stack.enter_context(
                patch("src.agent.tools.todoist_client.todoist_api_request", todo.api_request)
            )
            stack.enter_context(
                patch("src.agent.tools.todoist_client.todoist_sync_request", todo.sync_request)
            )
        if "garmin" in spec:
            g = spec["garmin"] or {}
            state = g.get("state", "connected")
            client = FakeGarmin(g.get("data") or {}) if state == "connected" else None
            fakes["garmin"] = client
            for module in ("src.agent.tools.garmin", "src.agent.tools.garmin_workout"):
                stack.enter_context(patch(f"{module}._get_garmin_client", lambda c=client: c))
            stack.enter_context(
                patch("src.agent.tools.garmin._persist_refreshed_tokens", lambda g: None)
            )
            if state != "connected":
                stack.enter_context(
                    patch(
                        "src.agent.tools.integration_status._was_connected",
                        lambda integration, s=state: s == "disconnected",
                    )
                )
        yield fakes


def describe_actions(fakes: dict[str, Any]) -> str:
    """Mutations the agent made through the fakes, for the judge."""
    lines = [a for fake in fakes.values() for a in getattr(fake, "actions", [])]
    return "\n".join(lines) if lines else "none"
