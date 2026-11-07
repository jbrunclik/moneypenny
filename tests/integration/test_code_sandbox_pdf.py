"""Live test: the sandbox image reads PDFs and names the pages without text.

A scanned page extracts no text; the overview must say so (and how to look
at the page) instead of returning silence. Runs only where Docker and the
sandbox image are available (skips otherwise, like the isolation test).
"""

import json

import pytest

from tests.integration.test_code_sandbox_isolation import _sandbox_runnable

_MIXED_PDF = """
from reportlab.lib.pagesizes import A4
from reportlab.pdfgen import canvas
c = canvas.Canvas('/work/t.pdf', pagesize=A4)
c.drawString(72, 750, 'Living room 4.20 m')
c.showPage()
c.showPage()
c.rect(72, 400, 200, 120)
c.showPage()
c.save()
import pdfplumber, pypdf
from sandbox_helpers import pdf_overview
print(pdf_overview('/work/t.pdf'))
print('TEXT1=' + pdfplumber.open('/work/t.pdf').pages[0].extract_text())
print('PAGES=' + str(len(pypdf.PdfReader('/work/t.pdf').pages)))
"""

_SCANNED_PDF = """
from reportlab.pdfgen import canvas
c = canvas.Canvas('/work/s.pdf')
c.rect(50, 50, 100, 100)
c.showPage()
c.rect(60, 60, 100, 100)
c.showPage()
c.save()
from sandbox_helpers import pdf_overview
pdf_overview('/work/s.pdf')
"""


def _run(code: str) -> dict:
    from src.agent.tools.code_execution import execute_code

    result = json.loads(execute_code.invoke({"code": code}))
    assert result.get("success") is True, f"sandbox execution failed: {result}"
    return result


@pytest.mark.skipif(not _sandbox_runnable(), reason="Docker or sandbox image unavailable")
def test_pdf_overview_names_the_pages_without_text() -> None:
    out = _run(_MIXED_PDF)["stdout"]

    assert "No text on pages 2-3" in out
    assert "TEXT1=Living room 4.20 m" in out
    assert "PAGES=3" in out


@pytest.mark.skipif(not _sandbox_runnable(), reason="Docker or sandbox image unavailable")
def test_pdf_overview_on_a_fully_scanned_pdf() -> None:
    out = _run(_SCANNED_PDF)["stdout"]

    assert "No page has text" in out
    assert "to_image(resolution=150)" in out


_LONG_PDF = """
from reportlab.pdfgen import canvas
c = canvas.Canvas('/work/long.pdf')
for i in range(3):
    c.drawString(72, 750, f'Sheet {i + 1}')
    c.showPage()
c.save()
from sandbox_helpers import pdf_overview
pdf_overview('/work/long.pdf', max_pages=2)
"""


@pytest.mark.skipif(not _sandbox_runnable(), reason="Docker or sandbox image unavailable")
def test_pdf_overview_stops_at_the_page_cap_and_says_so() -> None:
    """A long plan set must not run into the sandbox timeout with nothing
    printed: pages print as they are read, and the cap is named."""
    out = _run(_LONG_PDF)["stdout"]

    assert "page 2:" in out
    assert "page 3:" not in out
    assert "first 2 of 3 pages" in out
