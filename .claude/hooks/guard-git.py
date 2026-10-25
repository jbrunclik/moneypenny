#!/usr/bin/env python3
"""PreToolUse (Bash): keep parallel sessions from clobbering each other's work.

Several agent sessions share one checkout. A sweeping git command stages,
stashes or discards every session's changes, not just this one's, so stage
and restore explicit paths instead. Commit messages must follow Conventional
Commits (docs/conventions.md).

Exit 2 blocks the tool call and feeds stderr back to the model.
"""

import json
import re
import sys

# Heredoc bodies (commit messages, file contents) are data, not commands
_HEREDOC = re.compile(r"<<-?\s*(['\"]?)(\w+)\1[^\n]*\n(.*?)\n\s*\2\s*(?:\n|$)", re.DOTALL)
_SEGMENT_END = r"(?=\s|$|;|&|\|)"

_SWEEPING = [
    (
        re.compile(r"\bgit\s+add\b[^;&|\n]*?\s(-A|--all|-u|--update|\.|:/)" + _SEGMENT_END),
        "stages every session's changes",
    ),
    (
        re.compile(r"\bgit\s+commit\b[^;&|\n]*?\s(-a[a-zA-Z]*|--all)" + _SEGMENT_END),
        "commits every session's changes",
    ),
    (
        re.compile(r"\bgit\s+stash\b(?!\s+(list|show)\b)"),
        "stashes (and hides) every session's changes",
    ),
    (
        re.compile(r"\bgit\s+(checkout|restore)\b[^;&|\n]*?\s\." + _SEGMENT_END),
        "discards every session's changes",
    ),
    (re.compile(r"\bgit\s+reset\s+[^;&|\n]*--hard\b"), "discards every session's changes"),
    (re.compile(r"\bgit\s+clean\s+-\w*f"), "deletes every session's new files"),
]

_TYPES = "feat|fix|docs|style|refactor|test|chore|perf|build|ci|revert"
_CONVENTIONAL = re.compile(rf"^({_TYPES})(\([a-z0-9._/-]+\))?!?: \S")
_MESSAGE_FLAG = re.compile(r"\s(?:-m|--message)(?:\s+|=)(['\"])(.*?)\1", re.DOTALL)
_FILE_FROM_STDIN = re.compile(r"\s(?:-F|--file)(?:\s+|=)-(?=\s|$)")


def _commit_subject(command: str) -> str | None:
    """The subject line of a `git commit`, or None when it can't be read."""
    match = _MESSAGE_FLAG.search(command)
    if match:
        return match.group(2).strip().splitlines()[0] if match.group(2).strip() else ""
    if _FILE_FROM_STDIN.search(command):
        heredoc = _HEREDOC.search(command)
        if heredoc:
            lines = [line for line in heredoc.group(3).splitlines() if line.strip()]
            return lines[0].strip() if lines else ""
    return None


def check(command: str) -> str | None:
    """Why the command must not run, or None when it may."""
    bare = _HEREDOC.sub("\n", command)
    # Quoted strings that aren't git arguments (echo, grep) shouldn't match
    for pattern, harm in _SWEEPING:
        for match in pattern.finditer(bare):
            prefix = bare[: match.start()]
            if prefix.count("'") % 2 or prefix.count('"') % 2:
                continue
            return (
                f"`{match.group(0).strip()}` {harm}. Several sessions share this "
                "checkout: stage, restore or discard explicit paths only "
                "(git add <paths>, git checkout <path>), see AGENTS.md 'Parallel sessions'."
            )
    if re.search(r"\bgit\s+commit\b", bare) and "--no-edit" not in bare:
        subject = _commit_subject(command)
        if subject is not None and not _CONVENTIONAL.match(subject):
            return (
                f"Commit subject {subject!r} is not Conventional Commits: use "
                f"`type(scope): description` with type one of {_TYPES.replace('|', ', ')}."
            )
    return None


def main() -> int:
    try:
        payload = json.load(sys.stdin)
    except json.JSONDecodeError:
        return 0
    command = (payload.get("tool_input") or {}).get("command")
    if payload.get("tool_name") != "Bash" or not isinstance(command, str):
        return 0
    reason = check(command)
    if reason:
        print(reason, file=sys.stderr)
        return 2
    return 0


if __name__ == "__main__":
    sys.exit(main())
