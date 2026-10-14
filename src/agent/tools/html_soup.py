"""Parse a page with BeautifulSoup and free the tree when done.

A soup is a web of parent/sibling/next-element reference cycles, so reference
counting never frees it: each fetched page waited for the cyclic GC, and the
worker heap grew by whole pages that it never handed back (Oct 14 2026: a
2.5h worker held 26 parsed pages; collecting them freed 37 MB of objects but
none of its Pss).
"""

from collections.abc import Iterator
from contextlib import contextmanager

from bs4 import BeautifulSoup


@contextmanager
def parsed_html(html: str) -> Iterator[BeautifulSoup]:
    """Yield the parsed page; on exit, break its cycles so it is freed at once.

    Nothing taken from the tree may be used after the block: copy out plain
    strings (`str(...)`, `get_text()`) inside it.
    """
    soup = BeautifulSoup(html, "html.parser")
    try:
        yield soup
    finally:
        # decompose() walks next_element, which is empty on the root itself:
        # the top-level children must be decomposed one by one
        for child in list(soup.contents):
            child.decompose()
        soup.decompose()
