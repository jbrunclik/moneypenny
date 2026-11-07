"""Injection scan for persistent writes: memories, program KV data, facts.

Fetched pages are wrapped as untrusted, but what the model writes to storage
is injected into every later turn - a memory planted by a web page would
steer the assistant long after the page is gone. The scan refuses text that
reads as instructions to an AI, and characters a person cannot see.

It is anchored on attack vocabulary (instruction overrides, role hijacks,
fake prompt markup, requests for the system prompt, "send ... to http"),
not on bossy English: "Always answer in Czech" is a family member's
preference and must still save. Tests pin both directions
(tests/unit/test_threat_patterns.py).
"""

import re

# Zero-width, word-joiner and BOM characters, bidi embeddings/overrides and
# isolates, and Unicode tag characters: invisible in the UI, so they can hide
# instructions in plain sight. ZWJ (U+200D) and ZWNJ (U+200C) stay allowed -
# emoji sequences (a family emoji) and some scripts need them.
_INVISIBLE = re.compile("[​‎‏‪-‮⁠-⁤⁦-⁩﻿\U000e0000-\U000e007f]")

_INSTRUCTIONS = r"(?:instructions?|prompts?|rules|directions|guidelines|directives)"

# (reason, pattern); first match wins. Case-insensitive.
_PATTERNS: list[tuple[str, re.Pattern[str]]] = [
    (
        "instruction override",
        re.compile(
            r"\b(?:ignore|disregard|forget|override|bypass)\b[^.\n]{0,30}?"
            r"\b(?:all|any|the|your|my|these|those)?\s*"
            r"(?:previous|prior|above|earlier|preceding|existing|original|system)\s+"
            + _INSTRUCTIONS,
            re.IGNORECASE,
        ),
    ),
    (
        "instruction override",
        re.compile(r"\b(?:new|updated|override)\s+(?:system\s+)?instructions?\s*:", re.IGNORECASE),
    ),
    ("instruction override", re.compile(r"\bsystem\s+override\b", re.IGNORECASE)),
    (
        "role hijack",
        re.compile(
            r"\byou\s+are\s+now\s+(?:an?\s+)?(?:dan\b|jailbroken|unrestricted|unfiltered|in\s+developer\s+mode)"
            r"|\bdeveloper\s+mode\s+(?:enabled|on|activated)\b|\bjailbreak(?:ed)?\b",
            re.IGNORECASE,
        ),
    ),
    (
        "fake prompt markup",
        re.compile(
            r"<\s*/?\s*(?:system|assistant)\s*>|\[/?INST\]|<<\s*/?SYS\s*>>|<\|im_(?:start|end)\|>"
            r"|^\s*#{2,}\s*(?:system|instructions?)\b",
            re.IGNORECASE | re.MULTILINE,
        ),
    ),
    (
        "system prompt request",
        re.compile(
            r"\b(?:reveal|print|show|repeat|output|leak|disclose|dump)\b[^.\n]{0,40}?"
            r"\b(?:system\s+prompt|hidden\s+instructions|your\s+instructions)",
            re.IGNORECASE,
        ),
    ),
    (
        "exfiltration",
        re.compile(
            r"\b(?:send|post|forward|upload|exfiltrate|transmit|leak)\b[^\n]{0,80}?\bto\s+https?://"
            r"|!\[[^\]]*\]\(https?://[^)\s]*\?[^)\s]*=",
            re.IGNORECASE,
        ),
    ),
    # Czech: the family writes in Czech, and so may a page aimed at them
    (
        "instruction override",
        re.compile(
            r"\b(?:ignoruj|ignorujte|zapomeň|zapomeňte|nedbej)\b[^.\n]{0,30}?"
            r"\b(?:předchozí|dosavadní|výše\s+uvedené|původní)\s+(?:instrukce|pokyny|příkazy|pravidla)",
            re.IGNORECASE,
        ),
    ),
    (
        "system prompt request",
        re.compile(
            r"\b(?:prozraď|ukaž|vypiš|zopakuj)\b[^.\n]{0,30}?\bsystémov\w*\s+prompt", re.IGNORECASE
        ),
    ),
]


def find_injection(text: str) -> str | None:
    """Why `text` looks like a prompt injection, or None when it doesn't.

    The reason names the rule (and an invisible character's code point), never
    the matched text, so it is safe to log and to show the model.
    """
    invisible = _INVISIBLE.search(text)
    if invisible:
        return f"invisible or direction-changing character U+{ord(invisible.group()):04X}"
    for reason, pattern in _PATTERNS:
        if pattern.search(text):
            return f"looks like instructions to an AI ({reason})"
    return None
