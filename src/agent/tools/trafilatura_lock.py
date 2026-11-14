"""One lock around every trafilatura call.

trafilatura and htmldate parse with module-level lxml parsers
(`trafilatura.utils.HTML_PARSER`, `htmldate.utils.HTML_PARSER`), and an lxml
parser must not be used by two threads at once. research fetches its pages in
a thread pool, so two pages could be parsed together - production workers
died with `free(): invalid pointer` (SIGABRT) seconds into a research call on
Oct 28, Nov 11 and Nov 14 2026. Fetching stays parallel; only parsing (tens of
milliseconds per page) is serialized.
"""

import threading

TRAFILATURA_LOCK = threading.Lock()
