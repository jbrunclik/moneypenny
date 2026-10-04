---
name: product-research
description: Recommending products to buy or shops to buy from (what to get, which model, where it is cheapest or in stock). Load BEFORE recommending any product or shop.
---
# Product research and shopping help

## 1. Pin down the need first
- Budget, where they can buy (country/shipping region, preferred or excluded shops), size/fit/compatibility (model, dimensions, standards), must-have features, and deadline.
- Use what memory and this conversation already say; ask at most 2-3 short questions for what is missing, then research.

## 2. Offer deep research for a real comparison
- When `propose_deep_research` is available and the decision needs several products compared across shops and reviews (a budget plus a use case, "what should I get"), give a short first answer with 2-3 candidates, verified as in step 3, and call `propose_deep_research` in the same turn instead of researching a long list yourself.
- Skip the offer for a single product, a price or stock check, or when the user only wants a quick pick.

## 3. Recommend only what you verified
- Use `research` / `fetch_url` on live pages: every recommended item must be confirmed on a real product page that you read in this turn - it exists, it is the right category and spec, it ships to the user's region, and it is in stock.
- Never invent products, shops, prices or links. Never name a shop or price you did not read on a page in this turn - leave it out, or list it explicitly as unverified.
- Prefer shops the user can actually order from; for Czech users check Czech/EU shops first (e.g. Alza, Heureka for price comparison, the brand's own shop).

## 4. Present a decision, not a catalogue
- 2-4 options in a comparison table: name, price (with currency and date), where to buy (direct link), key differences, and the catch.
- Then one clear recommendation and why, tied to their stated needs.
- If nothing fits the constraints, say so and name the constraint to relax (budget, shop, feature).
- Do not end with a "Verified" summary: the app marks what the pages read do not back. Where something could not be checked (a page did not load, a price or stock status was not shown), say so right where you mention it.
