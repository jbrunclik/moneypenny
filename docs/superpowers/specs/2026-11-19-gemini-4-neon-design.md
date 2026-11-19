# Gemini 4 Neon as a middle tier - design (short)

**Intent.** Google released Gemini 4 Neon on Nov 18 2026 ($3 / $0.15 cached /
$15 per 1M tokens; Flex and Batch half). It sits between Hydrogen
($1.50/$7.50) and Carbon ($4/$20 from Dec 1 2026). Offer it as a third
picker model so admins can try it before the family gets it.

**Goals.**
- `gemini-4-neon` in `Config.MODELS` as "Gemini 4 Neon" / "Balanced",
  ordered Hydrogen, Neon, Carbon (the picker and the job editor follow MODELS).
- Admin-only (`ADMIN_ONLY_MODELS`), like Carbon.
- `"thinking_level": "medium"`. A probe (Nov 19 2026, the same trip-plan
  prompt twice per level) gave Neon's API default ~1,930 thinking tokens,
  more than its own `high` (~1,470); `medium` ~1,430 at ~28 s. At the default a
  call cost about what Carbon costs from Dec 1 (~$0.045). At `medium` it is
  ~20% cheaper. The freshness gate still overrides easy turns to `low` and
  hard ones to `high`.
- `MODEL_PRICING` row with no dated change.

**Non-goals.** No change to Carbon's thinking level (its default already sits
near `medium`: ~1,225 tokens). No Carbon job moves to Neon now: the eval judge
stays (it keeps scores comparable with `evals/history.jsonl`), memory defrag
stays (cents a night on Flex, and quality matters because it deletes
memories). No What's-new announcement while the model is admin-only.

**Approaches.** Plain config entry (chosen); the picker, job editor, access
rules and cost tracking all read config. A feature flag or env var would add a
knob nobody needs, because admin-only already limits the audience.

**Instrumentation (A8).** Per-model cost rows already exist. Add a
`docs/regular-review.md` check (Neon's cost per turn and thinking tokens
against Hydrogen and Carbon). Add TODO.md re-measures: around Dec 3 2026,
decide whether to open Neon to the family; after Dec 1, compare Neon (medium)
with Carbon as `DEEP_RESEARCH_WRITER_MODEL` on a few saved runs.

**Left to the builder.** Test placement, doc wording.
