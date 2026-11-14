"""create_artifact's description: when to build one.

Lives in the tool description, so it is only sent where the tool is bound. How
an artifact should look (sandbox rules, design system, bridge) is the
artifact-design skill, loaded only when one is made (~15 chat turns a month,
Nov 2026) instead of re-sent on every model call. Class names here and there
must match web/src/artifact/design-system.css
(web/tests/unit/artifact-design-system.test.ts checks both).
"""

CREATE_ARTIFACT_DESCRIPTION = """Show the user a small interactive or visual page (HTML/CSS/JS) inline below your reply. Reach for it in these cases:
- Checklists the user works through: packing lists, shopping or preparation lists, steps for a move or a trip. Use .mp-checklist and save the ticks with mp.state, so they survive reloads and other devices.
- Explainers: a structured guide when the answer has several parts to follow or compare - what each option does, doses or amounts, timing or a schedule, interactions, pros and cons, how something works. A card per item, a comparison table, .mp-tabs, .mp-stat for the key numbers.
- Recipes (always a card: ingredient checklist + numbered steps), calculators, converters, trackers, charts, timelines, small games.

Answer in prose instead for a short answer or a quick fact (a few sentences), for text the user will copy or edit (an email, a message, a translation, code), and for items going into Todoist or Calendar (use those tools). With an artifact, the reply itself is one or two sentences. To change an existing artifact use update_artifact (call read_artifact first if it was made in an earlier turn).

Before writing the html, call load_skill('artifact-design'): the sandbox rules, the app's design system classes and colour tokens, and the mp bridge.

title: short name in the user's language. html: the complete page."""
