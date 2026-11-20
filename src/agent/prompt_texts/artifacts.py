"""create_artifact's description: when to build one.

Lives in the tool description, so it is only sent where the tool is bound. How
an artifact should look (sandbox rules, design system, bridge) is the
artifact-design skill, loaded only when one is made (~15 chat turns a month,
Nov 2026) instead of re-sent on every model call. Class names here and there
must match web/src/artifact/design-system.css
(web/tests/unit/artifact-design-system.test.ts checks both).
"""

CREATE_ARTIFACT_DESCRIPTION = """Show the user a small interactive or visual page (HTML/CSS/JS) inline below your reply. Be proactive: make one without being asked whenever the answer is something the user will work through, compare or come back to, also in the middle of a conversation that has been prose so far, and also after you looked things up (research or search first, then present the findings as the artifact):
- Checklists the user works through: packing lists, shopping or preparation lists, what to buy for a project (a bill of materials), steps for a move or a trip. Use .mp-checklist: its ticks save themselves (reloads, other devices), and read_artifact tells you which items are done.
- Comparisons: two or more products, options, places or plans weighed against each other. A card per option or a comparison table, your recommendation on top.
- Step-by-step guides: how to set up, install, adjust, repair or make something, a workout with its exercises, a route or an itinerary. Numbered steps, what is needed first.
- Explainers and study guides: a structured guide when the answer has several parts to follow - what each option does, doses or amounts, timing or a schedule, interactions, pros and cons, how something works, material to learn for school. A card per item, .mp-tabs, .mp-stat for the key numbers.
- Recipes (always a card: ingredient checklist + numbered steps, also when the user asks for a meal idea and you answer with a dish), calculators, converters, trackers, charts, timelines, small games.

Answer in prose instead for a short answer or a quick fact (a few sentences), for an opinion or advice in conversation, for text the user will copy, edit or hand on (an email, a message, a post, a translation, code, a summary or prompt for another agent), and for items going into Todoist or Calendar (use those tools). With an artifact, the reply itself is one or two sentences. To change an existing artifact use update_artifact (call read_artifact first if it was made in an earlier turn).

Before writing the html, call load_skill('artifact-design'): the sandbox rules, the app's design system classes and colour tokens, and the mp bridge.

title: short name in the user's language. html: the complete page."""
