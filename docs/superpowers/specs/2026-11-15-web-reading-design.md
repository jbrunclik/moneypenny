# Web reading: blocked pages, faster research, longer and richer reads

Date: 2026-11-15. Size: project. Status: phase 1 shipped Nov 15 2026 (Exa
fallback); phase 2 (Reddit through its official API) dropped Nov 20 2026, Reddit
declined the request.

## Why

Answers about prices, shops, manuals and opinions are only as good as the pages
the agent can read. In the 30 days to Nov 15 2026, 27% of research page fetches
failed (937 of 3,475); 685 of the HTTP errors were 403s (Reddit 58, Alza 43,
Wikipedia 53, SRAM ~40, Yelp 30, Dr. Max 26, TripAdvisor 20, ManualsLib 14, a
long tail), 47 were 429s. This is likely a large part of why grounding flags
prices and shop names. Research is also slow: its searches run one after another
and one slow page can hold it for 90 s.

Measured Nov 15 2026:
- From the production host every User-Agent gets the same 403 from Reddit, SRAM,
  Alza, Dr. Max and ManualsLib (an address block or a bot challenge); Wikipedia
  answered 200 (its 403s come in bursts, last Nov 10).
- From home: SRAM and Wikipedia load; Alza, Dr. Max, Yelp, ManualsLib refuse
  even headless Chromium (a "one moment" challenge). Reddit answers 200 but a
  thread is an 8 KB JavaScript shell with no post or comments, `old.reddit.com`
  redirects logged-out visitors to a login page and `.json` is 403 - so a home
  route (a SOCKS proxy at home was designed, then dropped) cannot read
  Reddit either.
- Exa `/contents` read 9 of 10 failed URLs from the logs (Alza, Dr. Max x2,
  Hebe, TripAdvisor, two Wikipedias, a SRAM PDF, ManualsLib) in 3.9 s for
  $0.009; only Reddit failed (403 for Exa too). Tavily extract was not tested:
  its monthly credits are used up (432).

## Goals / non-goals / anti-goals

- Goals: a page that answers 403/429 is read anyway when another route can read
  it; Reddit threads are readable; research takes seconds, not minutes, on a
  slow page; a long page can be read past its cut; JSON, RSS/Atom feeds and PDFs
  are readable where they are refused today.
- Phase 2, gated: Reddit threads through Reddit's official API, built only
  once Reddit approves the app (Responsible Builder Policy, Nov 2025: new apps
  need approval, reportedly 2-4 weeks, personal use not guaranteed).
- Non-goals: a site-specific scraper per shop; the browser tool as a fetch
  fallback (headless Chromium is challenged too, and memory is tight); the
  Wikipedia API (the Exa fallback covers its bursts); Tavily extract (no
  credits; Exa is enough at this volume).
- Anti-goals: a fallback that silently empties Exa's monthly credit and benches
  Exa search; fetched text no longer framed as untrusted.

## Approaches

1. **Picked: direct fetch, then Exa `/contents` on 403/429; Reddit through
   its official API (phase 2).** Cheap (~23 blocked fetches a day, ~$0.70 a
   month of Exa's free $10), no new process on the production host.
2. Home proxy as the general fallback (free, but the home address is seen by
   every site, and it fails on the challenge sites anyway).
3. Browser tool fallback (challenged from both addresses; heavy).

For Reddit: its official API (picked, by the user) over a home route
(measured: no content logged out, even from home - see Why) or parking it.

## Design

### 1. Exa fallback for blocked pages

- `fetch_page_text` (research) and `fetch_url`: a direct fetch answering HTTP
  403 or 429 is retried once through Exa `/contents` (`text: true`, the
  caller's character limit), when Exa has a key, its breaker is not tripped,
  and its usage is below 90% of `SEARCH_QUOTA_EXA_MONTHLY` (the last 10% stays
  for search; builder's call after the builder check). Fallback failures do not
  feed the search breaker - except Exa saying it is out of credit (402), which
  sets the provider's exhausted flag as a search would.
- The result is the same shape as a direct read (HTML/text path), framed with
  `wrap_untrusted_content` as today; the page's own text, not Exa's summary.
- An Exa failure (its 403 `SOURCE_NOT_AVAILABLE`, a timeout, no credit) leaves
  today's error, naming both: "HTTP 403 when fetching X (also unavailable
  through the reading service)".
- Billing: Exa's usage counter is in $0.007 units (a search). Extract bills by
  the response's `costDollars` (~$0.001 a page): the fraction is carried in the
  kv store and whole units are added to `exa`'s monthly counter as they fill -
  never a whole unit per page (that would bench Exa search ~6x early).
- Timeout: Exa call `WEB_EXTRACT_TIMEOUT_SECONDS` = 15, on top of the direct
  fetch's own (so a research page takes at most ~30 s, against 90 today).

### 2. Reddit through its API (phase 2, dropped Nov 20 2026)

> **Dropped.** Reddit declined the request on Nov 20 2026: it no longer accepts
> public API access requests, and apps must run on its Developer Platform (apps
> that live inside Reddit, which does not fit an outside assistant reading a
> thread on demand). Reddit threads stay unreadable: logged out, Reddit serves no
> thread content to the production host, a home address or Exa (see Why). The
> design below is kept as the record of what was planned.

- The user applies for a Reddit API app (Developer Support form: a family
  assistant reading public threads on demand, a few dozen requests a day).
  Nothing is built until it is approved; TODO tracks the application.
- Once approved: a Reddit thread URL (`reddit.com`, any subdomain,
  `/r/<sub>/comments/<id>`) is read through the API with an app token
  (client credentials), rendered as text - title, post body, top comments by
  score with author and score, nested to a small depth - within the caller's
  character limit and framed as untrusted. Credentials in `.env` only
  (`REDDIT_CLIENT_ID`, `REDDIT_CLIENT_SECRET`, a descriptive User-Agent per
  Reddit's rules); empty = off, and a Reddit URL then fails as today, without
  an Exa attempt (Exa is refused too). Its own design pass when approved: the
  exact endpoints and limits come from the approval.

### 3. Faster research

- The searches of one `research` call run in parallel (as `web_search`'s batch
  does), keeping the rank interleaving and the failed-search count.
- Research page fetches get `RESEARCH_FETCH_TIMEOUT_SECONDS` = 15 instead of
  `TOOL_TIMEOUT_SECONDS` (90); `fetch_url` keeps 90 (the user asked for that
  page). A timed-out page is replaced like a failed one (the existing wave).

### 4. Longer and richer reads

- `fetch_url(url, start=0)`: a page cut at `HTML_TEXT_MAX_LENGTH` ends with
  "[Truncated at N of M characters - call fetch_url with start=N for more]";
  `start` returns the text from there. Its links: the page's links (text +
  absolute URL, deduplicated, at most `FETCH_URL_MAX_LINKS` = 40, navigation
  boilerplate left to the extractor) listed after the text when the page has
  any. The tool description grows by one line at most (the prompt-size work).
- JSON (`application/json`, `+json`) and XML/RSS/Atom (`application/xml`,
  `text/xml`, `+xml`) are read as text (pretty-printed JSON; feeds as text, no
  feed parser), with the text limits.
- PDFs: research sends a URL ending in `.pdf` straight to Exa `/contents`
  (text), and switches to Exa when a direct response turns out to be
  `application/pdf`; `fetch_url` checks `Content-Length` first and sends a PDF
  over `FETCH_URL_MAX_FILE_SIZE_BYTES` (2 MB) through Exa as text instead of
  refusing it (a missing header: after the download, as today). A small PDF in
  `fetch_url` stays multimodal. Same Exa gate as the fallback.

### Instrumented

- One "Page read via fallback" log line per fallback: `host`, `via`
  (`exa`; later `reddit`), `status` (`ok`/`failed`), `elapsed_ms`, `direct_status`
  (the 403/429), Exa `cost_usd`.
- "research completed" gains `search_ms` and `fetch_ms`.
- Regular review: fetch failure rate (baseline 27%, 937 of 3,475 in 30 days),
  fallbacks per week by `via` and outcome, Exa extract spend. TODO: re-measure ~Dec 1 2026.

## Left to the builder

The Exa extract adapter's place (next to the search adapters), the fractional
billing's kv keys, the domain matching helper, how `start` slices extracted
text, the link extraction (trafilatura or lxml on the already-parsed page), the
JSON pretty-print limits, test seams, and the order of commits.
