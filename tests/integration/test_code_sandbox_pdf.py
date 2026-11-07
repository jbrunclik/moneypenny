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
