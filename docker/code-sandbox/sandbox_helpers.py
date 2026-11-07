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


def pdf_overview(path: str) -> str:
    """Per page: size, text characters, words, vector drawing count, tables.

    Ends with which pages have no text. Prints the overview and returns it.
    """
    lines: list[str] = []
    empty: list[int] = []
    with pdfplumber.open(path) as pdf:
        for number, page in enumerate(pdf.pages, start=1):
            chars = len(page.chars)
            if chars == 0:
                empty.append(number)
            lines.append(
                f"page {number}: {page.width:.0f}x{page.height:.0f} pt, {chars} text chars, "
                f"{len(page.extract_words())} words, {len(page.lines) + len(page.rects)} lines/rects, "
                f"{len(page.find_tables())} tables"
            )
        total = len(pdf.pages)
    if not empty:
        lines.append("Every page has text.")
    elif len(empty) == total:
        lines.append(f"No page has text (scanned or drawn as images): {_RENDER_HINT}")
    else:
        lines.append(
            f"No text on pages {_ranges(empty)} (scanned or drawn as images): {_RENDER_HINT}"
        )
    overview = "\n".join(lines)
    print(overview)
    return overview
