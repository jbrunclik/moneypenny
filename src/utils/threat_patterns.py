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
import unicodedata

# Invisible in the UI, so they can hide instructions in plain sight: zero-width
# characters, the word joiner family and BOM, bidi marks, embeddings,
# overrides and isolates, invisible fillers (combining grapheme joiner, Hangul
# fillers, Mongolian vowel separator, Khmer inherent vowels) and Unicode tag
# characters and supplementary variation selectors. Raw string: `re` expands
# the escapes, and the source stays readable. Still allowed: ZWJ/ZWNJ
# (U+200D/U+200C - emoji sequences, some scripts), the emoji variation
# selectors (U+FE00-FE0F - the red heart) and the soft hyphen (pasted text);
# _for_matching strips them, so they cannot split a keyword either.
_INVISIBLE = re.compile(
    r"[\u034f\u061c\u115f\u1160\u17b4\u17b5\u180e\u200b\u200e\u200f\u202a-\u202e"
    r"\u2060-\u2064\u2066-\u2069\u3164\ufeff\uffa0\U000e0000-\U000e007f\U000e0100-\U000e01ef]"
)

# Variation selectors are combining marks (category Mn), not format characters
_VARIATION_SELECTORS = re.compile(r"[\ufe00-\ufe0f]")

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


def _for_matching(text: str) -> str:
    """`text` with keyword-splitting tricks undone: format characters (soft
    hyphen, ZWJ...) and variation selectors removed, lookalike forms
    (fullwidth letters, ligatures) folded by NFKC."""
    stripped = "".join(ch for ch in text if unicodedata.category(ch) != "Cf")
    return unicodedata.normalize("NFKC", _VARIATION_SELECTORS.sub("", stripped))


def find_injection(text: str) -> str | None:
    """Why `text` looks like a prompt injection, or None when it doesn't.

    The reason names the rule (and an invisible character's code point), never
    the matched text, so it is safe to log and to show the model.
    """
    invisible = _INVISIBLE.search(text)
    if invisible:
        return f"invisible or direction-changing character U+{ord(invisible.group()):04X}"
    folded = _for_matching(text)
    for reason, pattern in _PATTERNS:
        if pattern.search(folded):
            return f"looks like instructions to an AI ({reason})"
    return None
