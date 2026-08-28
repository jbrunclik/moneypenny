---
paths:
  - "web/**"
---

# Frontend conventions

- **State management**: [Zustand](https://github.com/pmndrs/zustand) (not Redux or custom) — [web/src/state/store.ts](../../web/src/state/store.ts).
- **Event delegation**: for dynamic content (not inline `onclick` — iOS Safari issues).
- **DOM**: `textContent` for plain text; `clearElement()` from [web/src/utils/dom.ts](../../web/src/utils/dom.ts).
- **Icons**: centralized in [web/src/utils/icons.ts](../../web/src/utils/icons.ts).
- **Named constants**: e.g. `DEFAULT_CONVERSATION_TITLE` from [web/src/types/api.ts](../../web/src/types/api.ts).
- **Enums (frontend)**: `as const` pattern in [web/src/types/api.ts](../../web/src/types/api.ts).
- **Add a UI component**: create a TypeScript file in `web/src/components/`, export init + render functions, and wire it in `main.ts`.
- **Test all UI changes on both desktop and mobile** — responsive layout with a 768px breakpoint.
- **Do not hand-edit** `web/src/types/generated-api.ts` — it is generated from the OpenAPI spec. Run `make types` to regenerate it; put hand-written types in `web/src/types/api.ts`.
