"""Helpers preinstalled in the code sandbox (on PYTHONPATH as `sandbox_helpers`).

pdf_overview() is the first look at a PDF: what each page holds, and which
pages came back with no text at all - scanned, or drawn as images - so the
model renders and looks at those instead of concluding they are blank.
"""

import pdfplumber

_RENDER_HINT = (
    "render them with pdfplumber page.to_image(resolution=150).save(...) and look at them."
)


def _ranges(pages: list[int]) -> str:
    """[2, 3, 7] -> '2-3, 7'."""
    spans: list[str] = []
    start = prev = pages[0]
    for page in pages[1:]:
        if page != prev + 1:
            spans.append(f"{start}-{prev}" if start != prev else str(start))
            start = page
        prev = page
    spans.append(f"{start}-{prev}" if start != prev else str(start))
    return ", ".join(spans)


def _page_line(number: int, page: "pdfplumber.page.Page") -> str:
    return (
        f"page {number}: {page.width:.0f}x{page.height:.0f} pt, {len(page.chars)} text chars, "
        f"{len(page.extract_words())} words, {len(page.lines) + len(page.rects)} lines/rects, "
        f"{len(page.find_tables())} tables"
    )


def _empty_note(empty: list[int], read: int) -> str:
    if not empty:
        return "Every page read has text."
    if len(empty) == read:
        return f"No page has text (scanned or drawn as images): {_RENDER_HINT}"
    return f"No text on pages {_ranges(empty)} (scanned or drawn as images): {_RENDER_HINT}"


def pdf_overview(path: str, max_pages: int = 20, first_page: int = 1) -> str:
    """Per page: size, text characters, words, vector drawing count, tables.

    Each page prints as soon as it is read (a slow, line-dense plan set must
    not hit the sandbox timeout with nothing shown), at most `max_pages` from
    `first_page`; it ends with which of them have no text. Returns the overview.
    """
    lines: list[str] = []
    empty: list[int] = []
    with pdfplumber.open(path) as pdf:
        total = len(pdf.pages)
        last = min(total, first_page + max_pages - 1)
        for number in range(first_page, last + 1):
            page = pdf.pages[number - 1]
            if not page.chars:
                empty.append(number)
            lines.append(_page_line(number, page))
            print(lines[-1], flush=True)
    read = last - first_page + 1
    notes = [_empty_note(empty, read)] if read > 0 else [f"The PDF has {total} pages; none from {first_page}."]
    if last < total:
        notes.append(
            f"Read the first {read} of {total} pages from page {first_page}: "
            f"pdf_overview(path, first_page={last + 1}) for the rest."
        )
    for note in notes:
        print(note, flush=True)
    return "\n".join(lines + notes)
