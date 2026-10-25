#!/usr/bin/env python3
"""PreToolUse (Bash): keep parallel sessions from clobbering each other's work.

Several agent sessions share one checkout. A sweeping git command stages,
stashes or discards every session's changes, not just this one's, so stage
and restore explicit paths instead. Commit messages must follow Conventional
Commits (docs/conventions.md, A1/A2).

The command is tokenized like a shell would (heredoc bodies removed, split on
;, &&, ||, |), so quoted text and git's global options (-C, -c) can't hide a
git call. This is a guardrail against mistakes, not a sandbox: `bash -c` or
`eval` strings aren't inspected. A command mentioning git that can't be
parsed is blocked rather than waved through.

Exit 2 blocks the tool call and feeds stderr back to the model.
"""

import json
import re
import shlex
import sys

_OPERATORS = {";", "&&", "||", "|", "&", "\n", "(", ")"}
_HEREDOC_START = re.compile(r"<<(-?)\s*(['\"]?)([A-Za-z_]\w*)\2")
_ASSIGNMENT = re.compile(r"^[A-Za-z_]\w*=")
# Global options before the subcommand; those listed in _GLOBAL_WITH_VALUE take one
_GLOBAL_WITH_VALUE = {"-C", "-c", "--git-dir", "--work-tree", "--namespace", "--exec-path"}
_SWEEPING_PATHSPECS = {".", "./", ":/", ":(top)", "*", ":/*"}

_TYPES = "feat|fix|docs|style|refactor|test|chore|perf|build|ci|revert"
_CONVENTIONAL = re.compile(rf"^({_TYPES})(\([a-z0-9._/-]+\))?!?: \S")


class ParseError(Exception):
    pass


def _placeholder(n: int) -> str:
    return f"__heredoc_{n}__"


def _strip_heredocs(command: str) -> tuple[str, list[str]]:
    """The command with each heredoc replaced by a placeholder token, and the bodies.

    The placeholder stays in its command's arguments, so a commit reads its
    own heredoc, not an earlier script's.
    """
    lines = command.split("\n")
    kept: list[str] = []
    bodies: list[str] = []
    i = 0
    while i < len(lines):
        line = lines[i]
        matches = list(_HEREDOC_START.finditer(line))
        for offset, match in enumerate(reversed(matches)):
            n = len(bodies) + len(matches) - 1 - offset
            line = line[: match.start()] + " " + _placeholder(n) + " " + line[match.end() :]
        kept.append(line)
        i += 1
        for match in matches:
            strip_tabs, delimiter = match.group(1) == "-", match.group(3)
            body: list[str] = []
            while i < len(lines):
                candidate = lines[i].lstrip("\t") if strip_tabs else lines[i]
                i += 1
                if candidate == delimiter:
                    break
                body.append(lines[i - 1])
            else:
                raise ParseError(f"heredoc {delimiter} is never closed")
            bodies.append("\n".join(body))
    return "\n".join(kept), bodies


def _segments(command: str) -> list[list[str]]:
    lexer = shlex.shlex(command, posix=True, punctuation_chars=";&|()\n")
    lexer.whitespace = " \t\r"
    lexer.whitespace_split = True
    segments: list[list[str]] = [[]]
    try:
        for token in lexer:
            if token in _OPERATORS or set(token) <= set(";&|()\n"):
                segments.append([])
            else:
                segments[-1].append(token)
    except ValueError as e:
        raise ParseError(str(e)) from e
    return [s for s in segments if s]


def _git_call(argv: list[str]) -> tuple[str, list[str]] | None:
    """(subcommand, its arguments) when the segment runs git, else None."""
    i = 0
    while i < len(argv) and _ASSIGNMENT.match(argv[i]):
        i += 1
    if i >= len(argv) or argv[i].rsplit("/", 1)[-1] != "git":
        return None
    i += 1
    while i < len(argv) and argv[i].startswith("-"):
        option = argv[i].split("=", 1)[0]
        i += 2 if option in _GLOBAL_WITH_VALUE and "=" not in argv[i] else 1
    if i >= len(argv):
        return None
    return argv[i], argv[i + 1 :]


def _flags(args: list[str]) -> tuple[set[str], list[str]]:
    """Short flags (clusters expanded), long flags, and the positional arguments."""
    flags: set[str] = set()
    positional: list[str] = []
    after_double_dash = False
    for arg in args:
        if after_double_dash or not arg.startswith("-") or arg == "-":
            positional.append(arg)
        elif arg == "--":
            after_double_dash = True
        elif arg.startswith("--"):
            flags.add(arg.split("=", 1)[0])
        else:
            flags.update(arg[1:])
    return flags, positional


def _sweep_reason(sub: str, args: list[str]) -> str | None:
    flags, positional = _flags(args)
    pathspec_sweeps = bool(_SWEEPING_PATHSPECS & set(positional))
    if sub == "add" and (flags & {"A", "u", "--all", "--update"} or pathspec_sweeps):
        return "stages every session's changes"
    if sub == "commit" and flags & {"a", "--all"}:
        return "commits every session's changes"
    if sub == "stash" and (not positional or positional[0] not in {"list", "show"}):
        return "stashes (and hides) every session's changes"
    if sub in {"checkout", "restore"} and pathspec_sweeps:
        return "discards every session's changes"
    if sub == "reset" and "--hard" in flags:
        return "discards every session's changes"
    if sub == "clean" and flags & {"f", "--force"}:
        return "deletes every session's new files"
    return None


def _commit_subject(args: list[str], heredocs: list[str]) -> str | None:
    """The commit's subject line; None when git would take it from elsewhere."""
    for i, arg in enumerate(args):
        if arg in {"-m", "--message", "-F", "--file"} and i + 1 < len(args):
            value = args[i + 1]
        elif arg.startswith("--message=") or arg.startswith("--file="):
            value = arg.split("=", 1)[1]
        elif arg.startswith("-m") and len(arg) > 2 and not arg.startswith("--"):
            value = arg[2:]
        else:
            continue
        if arg.startswith(("-F", "--file")):
            if value != "-":
                return None  # a message file: can't see it
            own = [heredocs[n] for n in range(len(heredocs)) if _placeholder(n) in args]
            value = own[0] if own else ""
        lines = [line.strip() for line in value.splitlines() if line.strip()]
        return lines[0] if lines else ""
    return None


def check(command: str) -> str | None:
    """Why the command must not run, or None when it may."""
    if "git" not in command:
        return None
    try:
        bare, heredocs = _strip_heredocs(command)
        segments = _segments(bare)
    except ParseError as e:
        return f"Couldn't parse this command to check its git calls ({e}); simplify it."
    for argv in segments:
        call = _git_call(argv)
        if call is None:
            continue
        sub, args = call
        harm = _sweep_reason(sub, args)
        if harm:
            return (
                f"`git {sub} {' '.join(args)}`".strip()
                + f" {harm}. Several sessions share this checkout: stage, restore or "
                "discard explicit paths only (git add <paths>, git checkout <path>), "
                "see AGENTS.md 'Parallel sessions'."
            )
        if sub == "commit" and "--no-edit" not in args:
            subject = _commit_subject(args, heredocs)
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
