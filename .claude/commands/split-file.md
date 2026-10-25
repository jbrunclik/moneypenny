---
description: Split a file or long function by responsibility, behavior unchanged
---

Split: $ARGUMENTS

Rules: `docs/conventions.md` "Size and structure" (C1). A split is a pure
refactor: behavior, public API and test results stay the same.

1. **Read the whole file** and list its responsibilities. Name each new module
   after what it does (`scroll-pinning.ts`), not its kind (`helpers.ts`).
2. **Pin behavior first.** If the parts you move lack direct tests, add
   characterization tests that pass on the current code before moving
   anything.
3. **Move in small commits**, one responsibility at a time. Update every import
   (no re-exports, C6) and keep the layer order (B1/F1): a moved piece that
   would import upward gets its dependency passed in instead.
4. **Long functions**: extract named helpers until each is under 50 lines and
   nested at most 3 deep.
5. **Verify after each move**: `make lint` and the relevant suite; the full
   suite (`make test-all` for frontend files) before the last commit.
6. **Docs**: update file paths in `docs/` pages and `.claude/rules/` that name
   the old file (`grep -rn <old name> docs .claude AGENTS.md`).
7. **TODO**: remove the file from "Split the files where bugs cluster" when done.
