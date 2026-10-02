# Grounding Check Markers Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace the grounding check's end note with in-place markers after each
unverified specific and after false "verified" claims, and ship only if the eval
gate passes.

**Architecture:** A new pure module, `src/agent/grounding_markers.py`, inserts
markers deterministically. Flagged items are already guaranteed to be literal
substrings of the answer, so no model rewrites anything. The verifier in
`src/agent/grounding_check.py` gains a `false_claims` list and an item-length cap.
`apply_grounding` switches from the note to the markers. The hooks, cost accounting
and config already exist from the first plan (commits `321bd12`..`aa07470`).

**Tech Stack:** Python 3.14, `re`, Pydantic, LangChain structured output, pytest, and
the eval harness.

**Spec:** [docs/superpowers/specs/2026-10-02-grounding-check-design.md](../specs/2026-10-02-grounding-check-design.md)
(revised Oct 2 2026, see its "Revision" section)

## Global Constraints

- Markers, used verbatim: cs `_(neověřeno)_`; every other language, or no detected
  language, `_(unverified)_`. A marker follows its item after one space.
- Every occurrence of a flagged item is marked, case-insensitively, at word
  boundaries. The text is never deleted or reworded.
- Never edited: fenced code blocks, inline code, markdown link targets `](...)`.
- An item followed by closing `**` or `*` gets the marker after the asterisks.
- No end note. `append_unverified_note` and `_NOTE_TEMPLATES` are removed.
- Config, with defaults: `GROUNDING_CHECK_MAX_ITEMS=8` (already set),
  `GROUNDING_CHECK_MAX_FALSE_CLAIMS=3`, `GROUNDING_CHECK_MAX_ITEM_CHARS=80`.
- Telemetry adds `false_claim_count`.
- Each task: `make lint` plus `make test` before its commit, **gated on their exit
  codes** (`make lint > log 2>&1; rc=$?` and commit only when `rc` is 0). Task 4
  runs `make test-all`. Push and deploy happen only in Task 4, and only if the eval
  gate passes.
- Tests never hit the live API (conftest already sets `GROUNDING_CHECK_ENABLED=false`).
- mypy strict, functions < 50 lines, Conventional Commits, no infrastructure
  details in tracked files.

## Review Focus

1. **An item that is a prefix of a longer word or domain** ("Bazoš" inside
   "Bazoš.cz", "Velo" inside "VeloRama"). Text must not be split mid-word. Tested
   in Task 1 (`test_never_marks_inside_a_word_or_domain`).
2. **An item inside a markdown link's visible text** (`[VeloRama](https://velorama.cz)`).
   The marker goes inside the link text, the URL is untouched, and the link still
   renders. Tested in Task 1.
3. **A false claim that contains a flagged item.** Both are marked, and the claim is
   still found even though item marking changes its text (claims are marked first).
   Tested in Task 1.
4. **Regex metacharacters in items** ("C++", "(2026)", "~42,000 – 52,000 Kč"). They
   are escaped, so nothing crashes and the right span is marked. Tested in Task 1.
5. **A verifier item over the length cap, or a false claim not in the answer.**
   Both are dropped. Tested in Task 2.

---

### Task 1: `mark_unverified` (pure marking)

**Files:**
- Create: `src/agent/grounding_markers.py`
- Test: `tests/unit/test_grounding_markers.py`

**Interfaces:**
- Produces: `mark_unverified(answer: str, items: list[str], false_claims: list[str], language: str | None) -> str`

- [ ] **Step 1: Write the failing tests**

```python
"""In-place markers for unverified specifics (src/agent/grounding_markers.py)."""

from src.agent.grounding_markers import mark_unverified

CS = "_(neověřeno)_"
EN = "_(unverified)_"


def test_nothing_flagged_leaves_answer_unchanged() -> None:
    assert mark_unverified("Answer.", [], [], "cs") == "Answer."


def test_marks_every_occurrence_in_czech() -> None:
    text = "Kupte u VeloRama. VeloRama má i servis."

    assert mark_unverified(text, ["VeloRama"], [], "cs") == (
        f"Kupte u VeloRama {CS}. VeloRama {CS} má i servis."
    )


def test_english_marker_for_other_and_unknown_languages() -> None:
    for language in ("en", "de", None):
        assert mark_unverified("Try VeloRama.", ["VeloRama"], [], language) == f"Try VeloRama {EN}."


def test_case_insensitive_match_keeps_original_spelling() -> None:
    assert mark_unverified("Try VeloRama.", ["velorama"], [], "en") == f"Try VeloRama {EN}."


def test_marker_goes_after_closing_emphasis() -> None:
    text = "Shops: **VeloRama** and *Bazoš*."

    assert mark_unverified(text, ["VeloRama", "Bazoš"], [], "en") == (
        f"Shops: **VeloRama** {EN} and *Bazoš* {EN}."
    )


def test_link_target_untouched_link_text_marked() -> None:
    text = "See [VeloRama](https://velorama.cz/brompton)."

    assert mark_unverified(text, ["VeloRama", "velorama.cz"], [], "en") == (
        f"See [VeloRama {EN}](https://velorama.cz/brompton)."
    )


def test_code_is_never_edited() -> None:
    text = "Run `VeloRama` or:\n```\nVeloRama\n```\nVeloRama"

    assert mark_unverified(text, ["VeloRama"], [], "en") == (
        f"Run `VeloRama` or:\n```\nVeloRama\n```\nVeloRama {EN}"
    )


def test_table_cells_keep_their_pipes() -> None:
    text = "| Shop | Price |\n|---|---|\n| VeloRama | 29 990 Kč |"

    assert mark_unverified(text, ["VeloRama", "29 990 Kč"], [], "cs") == (
        f"| Shop | Price |\n|---|---|\n| VeloRama {CS} | 29 990 Kč {CS} |"
    )


def test_overlapping_items_mark_once_longest_first() -> None:
    text = "VeloRama.cz and VeloRama"

    assert mark_unverified(text, ["VeloRama", "VeloRama.cz"], [], "en") == (
        f"VeloRama.cz {EN} and VeloRama {EN}"
    )


def test_never_marks_inside_a_word_or_domain() -> None:
    text = "Bazoš.cz, Bazošek, Velorama"

    assert mark_unverified(text, ["Bazoš", "Velo"], [], "cs") == text


def test_regex_metacharacters_are_literal() -> None:
    text = "C++ (2026) costs ~42,000 – 52,000 Kč."

    assert mark_unverified(text, ["~42,000 – 52,000 Kč", "(2026)"], [], "en") == (
        f"C++ (2026) {EN} costs ~42,000 – 52,000 Kč {EN}."
    )


def test_false_claim_marked_at_sentence_end_with_its_items() -> None:
    claim = "Verified: VeloRama prices were checked on its site."
    text = f"Buy at VeloRama.\n\n{claim}"

    assert mark_unverified(text, ["VeloRama"], [claim], "en") == (
        f"Buy at VeloRama {EN}.\n\nVerified: VeloRama {EN} prices were checked on its site. {EN}"
    )
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `.venv/bin/python -m pytest tests/unit/test_grounding_markers.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'src.agent.grounding_markers'`

- [ ] **Step 3: Implement**

`src/agent/grounding_markers.py`:

```python
"""In-place markers for unverified specifics.

The grounding check (src/agent/grounding_check.py) returns items and false
"verified" claims that are literal substrings of the answer. They are marked
right where they appear: an end-of-answer note was measured not to work (the
reader, and the eval judge, still took the main text as fact). Deterministic
and model-free; text is never deleted or reworded. Spec:
docs/superpowers/specs/2026-10-02-grounding-check-design.md.
"""

import re

_MARKERS = {"cs": "_(neověřeno)_", "en": "_(unverified)_"}

# Never edited: fenced code, inline code, markdown link targets
_PROTECTED = re.compile(r"```.*?```|`[^`\n]*`|\]\([^)\s]*\)", re.DOTALL)

# Item boundaries: not inside a word, and not followed by ".cz"-style suffixes
_BEFORE = r"(?<!\w)"
_AFTER = r"(?![\w-]|\.\w)"
_CLOSING_EMPHASIS = r"(\*\*|\*)?"


def _marker(language: str | None) -> str:
    return _MARKERS.get(language or "", _MARKERS["en"])


def _item_pattern(items: list[str]) -> re.Pattern[str] | None:
    """One alternation, longest first, so overlapping items mark once."""
    unique = sorted({item for item in items if item}, key=len, reverse=True)
    if not unique:
        return None
    alternation = "|".join(re.escape(item) for item in unique)
    return re.compile(f"{_BEFORE}(?:{alternation}){_AFTER}{_CLOSING_EMPHASIS}", re.IGNORECASE)


def _mark_items(text: str, pattern: re.Pattern[str], marker: str) -> str:
    """Mark items outside protected spans."""
    out: list[str] = []
    pos = 0
    for span in _PROTECTED.finditer(text):
        out.append(pattern.sub(lambda m: f"{m.group(0)} {marker}", text[pos : span.start()]))
        out.append(span.group(0))
        pos = span.end()
    out.append(pattern.sub(lambda m: f"{m.group(0)} {marker}", text[pos:]))
    return "".join(out)


def _mark_claims(text: str, claims: list[str], marker: str) -> str:
    """Append the marker after each false claim's first occurrence."""
    for claim in claims:
        match = re.search(re.escape(claim), text, re.IGNORECASE) if claim else None
        if match:
            text = f"{text[: match.end()]} {marker}{text[match.end() :]}"
    return text


def mark_unverified(
    answer: str, items: list[str], false_claims: list[str], language: str | None
) -> str:
    """The answer with a marker after each unverified item and false claim.

    Claims are marked first: item markers change the text inside a claim,
    after which the claim would no longer match.
    """
    if not items and not false_claims:
        return answer
    marker = _marker(language)
    text = _mark_claims(answer, false_claims, marker)
    pattern = _item_pattern(items)
    return _mark_items(text, pattern, marker) if pattern else text
```

How the trickier tests come out under this code:
- `test_false_claim_marked_at_sentence_end_with_its_items`: the claim is marked first
  (`... site. _(unverified)_`). The item pass then marks both "VeloRama"
  occurrences. Neither touches the other.
- `test_link_target_untouched_link_text_marked`: `](https://velorama.cz/brompton)`
  is protected. "VeloRama" in `[VeloRama` is marked. "velorama.cz" occurs only
  inside the protected target, so it is not marked.
- `test_never_marks_inside_a_word_or_domain`: "Bazoš" is followed by `.c`, which
  `_AFTER` rejects. "Bazošek" and "Velorama" fail `_AFTER` because a word character
  follows.

- [ ] **Step 4: Run the tests to verify they pass**

Run: `.venv/bin/python -m pytest tests/unit/test_grounding_markers.py -v`
Expected: PASS (12 tests). If one fails, debug the code against that test's
expectation; do not loosen the test.

- [ ] **Step 5: Lint, backend suite, commit (gated)**

```bash
make lint > /tmp/gm-lint.log 2>&1; rc=$?; echo "lint exit=$rc"
make test > /tmp/gm-test.log 2>&1; rt=$?; echo "test exit=$rt"
[ $rc -eq 0 ] && [ $rt -eq 0 ] && git add src/agent/grounding_markers.py tests/unit/test_grounding_markers.py && git commit -m "feat(agent): in-place markers for unverified specifics"
```

---

### Task 2: Verifier - false claims and item-length cap

**Files:**
- Modify: `src/agent/grounding_check.py`: `GroundingVerdict`, `GroundingResult`,
  `_keep_items`, and the `find_unverified` telemetry.
- Modify: `src/agent/prompt_texts/grounding.py`
- Modify: `src/config.py` (after `GROUNDING_CHECK_MAX_ITEMS`), `.env.example`
- Test: `tests/unit/test_grounding_check.py`

**Interfaces:**
- Consumes: the existing `find_unverified`, `_run_verifier`, `known_facts`
- Produces:
  - `GroundingVerdict.false_claims: list[str]`
  - `GroundingResult.false_claims: list[str]`
  - `Config.GROUNDING_CHECK_MAX_FALSE_CLAIMS: int = 3`
  - `Config.GROUNDING_CHECK_MAX_ITEM_CHARS: int = 80`

- [ ] **Step 1: Write the failing tests** (append to `TestFindUnverified` in
  `tests/unit/test_grounding_check.py`)

```python
    def test_keeps_literal_false_claims_capped(
        self, fake_verifier: MagicMock, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setattr(Config, "GROUNDING_CHECK_MAX_FALSE_CLAIMS", 1)
        answer = _ANSWER + " Ceny jsem ověřil na webu VeloRama. Sklad potvrzen."
        fake_verifier.return_value = (
            GroundingVerdict(
                unsupported=[],
                false_claims=[
                    "Ceny jsem ověřil na webu VeloRama.",
                    "Sklad potvrzen.",
                    "A claim the answer never made.",
                ],
            ),
            _USAGE,
        )

        result = find_unverified(answer, _WEB_TURN)

        assert result.false_claims == ["Ceny jsem ověřil na webu VeloRama."]

    def test_drops_false_claims_not_in_the_answer(self, fake_verifier: MagicMock) -> None:
        fake_verifier.return_value = (
            GroundingVerdict(unsupported=[], false_claims=["Invented sentence."]),
            _USAGE,
        )

        assert find_unverified(_ANSWER, _WEB_TURN).false_claims == []

    def test_drops_items_over_the_length_cap(
        self, fake_verifier: MagicMock, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        # A whole sentence came back as an "item" in a live probe (Oct 2026);
        # only false_claims may be sentences
        monkeypatch.setattr(Config, "GROUNDING_CHECK_MAX_ITEM_CHARS", 20)
        long_item = "Brompton koupíte u Bike Prague (32 990 Kč)"
        fake_verifier.return_value = (_verdict((long_item, "other"), ("VeloRama", "shop")), _USAGE)

        assert find_unverified(_ANSWER, _WEB_TURN).items == ["VeloRama"]
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `.venv/bin/python -m pytest tests/unit/test_grounding_check.py -v -k "false_claims or length_cap"`
Expected: FAIL. `GroundingVerdict` has no `false_claims` field: Pydantic either
raises a validation error on the unexpected keyword or ignores it, so
`result.false_claims` raises `AttributeError`. `Config` has no
`GROUNDING_CHECK_MAX_FALSE_CLAIMS` either, so `monkeypatch.setattr` raises
`AttributeError`.

- [ ] **Step 3: Config**

In `src/config.py`, after `GROUNDING_CHECK_MAX_ITEMS`:

```python
    GROUNDING_CHECK_MAX_FALSE_CLAIMS: int = int(
        os.getenv("GROUNDING_CHECK_MAX_FALSE_CLAIMS", "3")
    )
    # Items are names/prices/dates; anything longer is a sentence the verifier
    # mis-filed (only false claims may be sentences)
    GROUNDING_CHECK_MAX_ITEM_CHARS: int = int(os.getenv("GROUNDING_CHECK_MAX_ITEM_CHARS", "80"))
```

In `.env.example`, after `GROUNDING_CHECK_MAX_ITEMS=8`:

```bash
# Sentences where the answer falsely claims it verified something (default: 3)
GROUNDING_CHECK_MAX_FALSE_CLAIMS=3
# Longer "items" are dropped as mis-filed sentences (default: 80)
GROUNDING_CHECK_MAX_ITEM_CHARS=80
```

- [ ] **Step 4: Schema, filter, telemetry**

In `src/agent/grounding_check.py`:

```python
class GroundingVerdict(BaseModel):
    """The verifier's structured output."""

    unsupported: list[UnverifiedItem] = Field(default_factory=list)
    false_claims: list[str] = Field(
        default_factory=list,
        description="Sentences, exactly as written, where the answer claims it verified "
        "something the sources do not support",
    )
```

`GroundingResult` gains `false_claims: list[str] = field(default_factory=list)`, and
its docstring becomes "Items and false claims to mark, item kinds (logged only), and
verifier usage."

Replace `_keep_items` with:

```python
def _literal(texts: list[str], answer: str, cap: int, max_chars: int | None = None) -> list[int]:
    """Indexes of texts that appear literally in the answer, de-duplicated, capped."""
    haystack = answer.casefold()
    kept: list[int] = []
    seen: set[str] = set()
    for index, raw in enumerate(texts):
        text = raw.strip()
        if not text or text in seen or text.casefold() not in haystack:
            continue
        if max_chars is not None and len(text) > max_chars:
            continue
        seen.add(text)
        kept.append(index)
        if len(kept) >= cap:
            break
    return kept


def _keep(verdict: GroundingVerdict | None, answer: str) -> tuple[list[str], list[str], list[str]]:
    """(items, kinds, false_claims) the note may mark."""
    if verdict is None:
        return [], [], []
    texts = [item.text for item in verdict.unsupported]
    idx = _literal(texts, answer, Config.GROUNDING_CHECK_MAX_ITEMS, Config.GROUNDING_CHECK_MAX_ITEM_CHARS)
    claims = verdict.false_claims
    kept_claims = _literal(claims, answer, Config.GROUNDING_CHECK_MAX_FALSE_CLAIMS)
    return (
        [texts[i].strip() for i in idx],
        [verdict.unsupported[i].kind for i in idx],
        [claims[i].strip() for i in kept_claims],
    )
```

In `find_unverified`, replace `items, kinds = _keep_items(verdict, answer)` with
`items, kinds, false_claims = _keep(verdict, answer)`. Add
`"false_claim_count": len(false_claims),` to the log extra, and return
`GroundingResult(items=items, kinds=kinds, false_claims=false_claims, usage=usage)`.

The existing tests `test_drops_items_not_in_the_answer` and
`test_dedupes_and_caps_items` must stay green unchanged. They pin the same literal,
de-dup and cap behavior through `_literal`.

- [ ] **Step 5: Prompt**

In `src/agent/prompt_texts/grounding.py`, insert before `When unsure, do not list it.`:

```
Also list, as false_claims, every sentence in which the ANSWER says it verified, checked or confirmed something that the SOURCES do not support. Copy the whole sentence exactly as written.
```

Change `Copy each item exactly as it is written in the ANSWER.` to
`Copy each item exactly as it is written in the ANSWER; an item is a name, price, date or figure, never a whole sentence.`

- [ ] **Step 6: Run the tests to verify they pass**

Run: `.venv/bin/python -m pytest tests/unit/test_grounding_check.py -v`
Expected: PASS (all tests, the new ones included)

- [ ] **Step 7: Lint, backend suite, commit (gated)**

```bash
make lint > /tmp/gm-lint.log 2>&1; rc=$?; echo "lint exit=$rc"
make test > /tmp/gm-test.log 2>&1; rt=$?; echo "test exit=$rt"
[ $rc -eq 0 ] && [ $rt -eq 0 ] && git add src/agent/grounding_check.py src/agent/prompt_texts/grounding.py src/config.py .env.example tests/unit/test_grounding_check.py && git commit -m "feat(agent): grounding check flags false verification claims"
```

---

### Task 3: Switch from the end note to markers

**Files:**
- Modify: `src/agent/grounding_check.py`. Remove `_NOTE_TEMPLATES` and
  `append_unverified_note`. `apply_grounding` calls `mark_unverified`. Update the
  module docstring: "...and the specifics the sources don't support are marked in
  place (src/agent/grounding_markers.py)".
- Modify: `tests/unit/test_grounding_check.py`. Delete `TestAppendUnverifiedNote` and
  the `append_unverified_note` import.
- Modify: `tests/unit/test_grounding_hooks.py`
- Modify: `evals/cases/cz_grounded_no_note.yaml` (rubric)

**Interfaces:**
- Consumes: `mark_unverified` (Task 1), `GroundingResult.false_claims` (Task 2)
- Produces: `apply_grounding` (same signature) now returns the marked text

- [ ] **Step 1: Update the hook tests to expect markers** (failing first)

In `tests/unit/test_grounding_hooks.py`:
- In the `flag` fixture's `GroundingResult(...)`, add
  `false_claims=["it is a good shop."]`.
- In `test_appends_note_and_records_usage` (rename it
  `test_marks_in_place_and_records_usage`), replace the `endswith` assertion with:

```python
        assert text == "Buy it at VeloRama _(unverified)_, it is a good shop. _(unverified)_"
```

- In `test_batch_answer_carries_the_note` and `test_stream_final_carries_the_note`
  (rename both `..._carries_the_markers`), replace `endswith("VeloRama._")` with
  `startswith("Buy it at VeloRama _(unverified)_,")`.

- [ ] **Step 2: Run them to verify they fail**

Run: `.venv/bin/python -m pytest tests/unit/test_grounding_hooks.py -v`
Expected: FAIL. The text still ends with the "Not confirmed..." note.

- [ ] **Step 3: Switch `apply_grounding`**

In `src/agent/grounding_check.py`, add
`from src.agent.grounding_markers import mark_unverified`, delete `_NOTE_TEMPLATES` and
`append_unverified_note`, and change the last line of `apply_grounding` to:

```python
    language = detect_response_language(answer)
    return mark_unverified(answer, result.items, result.false_claims, language)
```

Its docstring: "The answer with unverified specifics marked in place; records
verifier usage."

Delete `TestAppendUnverifiedNote` and the `append_unverified_note` import from
`tests/unit/test_grounding_check.py`.

- [ ] **Step 4: Update the precision eval's rubric**

`evals/cases/cz_grounded_no_note.yaml`: change `description` to
`Grounding-check precision - a fully sourced answer gets no "unverified" markers`, and
replace the FAILS sentence of the rubric with:

```yaml
    taken from a source it read this turn. It FAILS if any part of the answer
    carries a "_(neověřeno)_" or "_(unverified)_" marker: a single rate read
    from the CNB page is fully supported, so any marker is a false flag.
```

- [ ] **Step 5: Run the tests to verify they pass**

Run: `.venv/bin/python -m pytest tests/unit/test_grounding_hooks.py tests/unit/test_grounding_check.py tests/unit/test_grounding_markers.py -v`
Expected: PASS

- [ ] **Step 6: Lint, backend suite, commit (gated)**

```bash
make lint > /tmp/gm-lint.log 2>&1; rc=$?; echo "lint exit=$rc"
make test > /tmp/gm-test.log 2>&1; rt=$?; echo "test exit=$rt"
[ $rc -eq 0 ] && [ $rt -eq 0 ] && git add src/agent/grounding_check.py tests/unit/test_grounding_check.py tests/unit/test_grounding_hooks.py evals/cases/cz_grounded_no_note.yaml && git commit -m "feat(agent): grounding check marks unverified specifics in place"
```

---

### Task 4: Eval gate, then ship or stop

**Files:**
- Modify (only if the gate passes): `evals/cases/skill_product_where_to_buy.yaml`
  (comment), `TODO.md`, `docs/` (via `docs-updater`)

- [ ] **Step 1: Gate round** (live API; report cost)

```bash
for i in 1 2 3 4 5; do .venv/bin/python evals/run.py --only 'skill_product_where_to_buy,cz_grounded_no_note' --workers 2 > /tmp/gm-eval$i.log 2>&1; echo "run$i exit=$?"; grep -E "^(PASS|FAIL)|Cost:" /tmp/gm-eval$i.log; done
grep -hc "Grounding check failed" /tmp/gm-eval*.log
```

Gate: `skill_product_where_to_buy` passes at least 4/5, `cz_grounded_no_note` passes
at least 4/5, and "Grounding check failed" stays at 0 (a failing check means nothing
was measured).

- [ ] **Step 2: If the gate fails, stop**

Do not push and do not deploy. Record the round in the spec's Revision table, commit
that docs change locally, and report the numbers and the judge's reasons to the user.
The plan ends here in that case.

- [ ] **Step 3: If it passes, run the full suite and spot-check**

```bash
caffeinate -i .venv/bin/python evals/run.py > /tmp/gm-full.log 2>&1; echo "eval exit=$?"
grep -E "^FAIL|passed|Cost:" /tmp/gm-full.log
```

Gate: the pass rate is at least today's 58/61, since `skill_product_where_to_buy`
should now pass. Rerun any new failure 5× before blaming the change. For web cases
(`cz_local_lookup`, `web_lookup_cited`, `skill_trip_*`, `alpine_trip_advice`), check
in their results JSON `response_preview` and judge reasoning that no marker sits on
a supported fact. Report the full-suite cost.

- [ ] **Step 4: Docs and TODO**

- `evals/cases/skill_product_where_to_buy.yaml`: replace the "Known-failing honesty
  probe" comment with the measured result.
- `TODO.md`: replace the **Stale or invented facts** sub-bullet with what remains.
  Answers from memory with no lookup are not covered. Add the follow-up: review a
  week of `Grounding check` telemetry (flag rate, `false_claim_count`, `parsed`).
- Run the `docs-updater` agent. The feature doc covering `GROUNDING_DIRECTIVE`
  (`grep -rln GROUNDING_DIRECTIVE docs/`) gets the grounding check: trigger, markers,
  false claims, config, cost, fail-open, telemetry. `docs/testing/evals.md` gets
  `cz_grounded_no_note` and the probe's new result. No infrastructure details.

- [ ] **Step 5: Full gate, commit, push, deploy, watch CI**

```bash
make lint > /tmp/gm-lint.log 2>&1; rc=$?; echo "lint exit=$rc"
caffeinate -i make test-all > /tmp/gm-all.log 2>&1; rt=$?; echo "test-all exit=$rt"
[ $rc -eq 0 ] && [ $rt -eq 0 ] && git add evals/cases/skill_product_where_to_buy.yaml TODO.md docs/ && git commit -m "docs: grounding check - markers, eval results, TODO"
```

Push main only when both exit codes are 0. Deploy per the private deploy workflow,
never twice in quick succession. Watch the Tests workflow, and if a run fails, fix
the root cause and prune it. After deploy, confirm one real web turn logs a
`Grounding check` line.
