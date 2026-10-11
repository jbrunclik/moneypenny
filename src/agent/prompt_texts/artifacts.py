"""create_artifact's description: when to build one and how it should look.

Lives in the tool description, so it is only sent where the tool is bound.
Keep it near 400 tokens; the class list must match web/src/artifact/design-system.css
(web/tests/unit/artifact-design-system.test.ts checks it).
"""

CREATE_ARTIFACT_DESCRIPTION = """Show the user a small interactive or visual page (HTML/CSS/JS) inline below your reply: calculators, converters, recipe cards with ingredient checklists, trackers, charts, timelines, small games.

Use it only when interacting or seeing it beats reading - NEVER for plain answers, lists, tables or code the user asked to read. A recipe is always a card (ingredient checklist + numbered steps): the user cooks from it. To change an existing artifact use update_artifact (call read_artifact first if it was made in an earlier turn).

It runs sandboxed: no network, no external URLs (images only inline SVG or data: URIs), no localStorage. Write a fragment (no <html>/<head> needed). The app's design system is already loaded:
- Bare elements are styled: h1-h3, p, a, button (add class "secondary"), input, select, input[type=range], table, ul/ol, code/pre.
- Layout: .mp-stack (vertical gap), .mp-row (horizontal, wraps), .mp-grid (auto columns), .mp-divider.
- Components: .mp-card, .mp-hero (title block), .mp-stat (<div class="mp-stat"><span>Label</span><strong>42</strong></div>), .mp-chip, .mp-checklist (ul of <li><label><input type=checkbox> text</label></li>), .mp-steps (ol), .mp-tabs (radio+label pairs, then one .mp-tab-panel div per tab in the same order), .mp-muted, .mp-accent.
- Colours only via var(--mp-text|--mp-muted|--mp-accent|--mp-surface|--mp-border|--mp-success|--mp-warning|--mp-error) or currentColor - never hex. It must look right in light and dark.
- Sizing: fluid only (%, fr, minmax, flex). No fixed widths or heights. SVG: viewBox plus width="100%". It must work from 320px phone width to desktop.

Bridge (global mp):
- mp.send(text): send text as the user's next message (only from a click handler).
- await mp.state.get() / mp.state.set(obj): save small JSON (ticked items, scores); it survives reloads and other devices.
- mp.theme ('light'|'dark') and window 'mp:theme' event.

Example: <div class="mp-card mp-stack"><h2>Tip</h2><input id="b" type="number" placeholder="Bill"><div class="mp-stat"><span>Tip 10%</span><strong id="t">0</strong></div></div><script>b.oninput=()=>t.textContent=(b.value*0.1).toFixed(2)</script>

title: short name in the user's language. html: the complete page."""
