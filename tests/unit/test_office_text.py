"""Office uploads read as text (Nov 16 2026): Gemini cannot take docx, xlsx
or pptx, so the agent sees their text in the message, and the original stays
available to the sandbox for edits."""

from __future__ import annotations

import io
import re
import time
import zipfile
from collections.abc import Callable
from datetime import UTC, datetime

import docx
import openpyxl
import pytest
from pptx import Presentation

from src.config import Config
from src.utils.office_text import DOCX, PPTX, XLSX, OfficeReadError, office_text


def _docx() -> bytes:
    document = docx.Document()
    document.add_heading("Trip plan", level=1)
    document.add_paragraph("We leave on Friday.")
    table = document.add_table(rows=2, cols=2)
    table.cell(0, 0).text, table.cell(0, 1).text = "day", "place"
    table.cell(1, 0).text, table.cell(1, 1).text = "Fri", "Brno"
    out = io.BytesIO()
    document.save(out)
    return out.getvalue()


def _xlsx() -> bytes:
    book = openpyxl.Workbook()
    sheet = book.active
    assert sheet is not None
    sheet.title = "Budget"
    sheet.append(["item", "cost"])
    sheet.append(["tent", 120])
    # Written by a script, never opened in Excel: no cached value
    sheet["C2"] = "=B2*2"
    book.create_sheet("Notes").append(["bring water"])
    out = io.BytesIO()
    book.save(out)
    return out.getvalue()


def _pptx() -> bytes:
    deck = Presentation()
    for title in ["Intro", "Plan"]:
        slide = deck.slides.add_slide(deck.slide_layouts[1])
        slide.shapes.title.text = title
    deck.slides[1].notes_slide.notes_text_frame.text = "Mention the budget"
    out = io.BytesIO()
    deck.save(out)
    return out.getvalue()


def test_word_keeps_headings_paragraphs_and_tables() -> None:
    result = office_text(_docx(), DOCX)
    assert "# Trip plan" in result.text
    assert "We leave on Friday." in result.text
    assert "| Fri | Brno |" in result.text
    assert result.truncated is False


def test_excel_lists_each_sheet_with_values_and_uncached_formulas() -> None:
    text = office_text(_xlsx(), XLSX).text
    assert "## Sheet: Budget" in text
    assert "| tent | 120 | =B2*2 |" in text
    assert "## Sheet: Notes" in text
    assert "None" not in text


def test_powerpoint_lists_slides_and_notes() -> None:
    text = office_text(_pptx(), PPTX).text
    assert "## Slide 1" in text
    assert "## Slide 2" in text
    assert "Plan" in text
    assert "Notes: Mention the budget" in text


def test_long_text_is_cut_at_the_cap(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(Config, "OFFICE_TEXT_MAX_CHARS", 30)
    result = office_text(_docx(), DOCX)
    assert len(result.text) <= 30
    assert result.truncated is True


def test_a_zip_bomb_is_refused_before_parsing(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(Config, "OFFICE_MAX_UNCOMPRESSED_BYTES", 1000)
    out = io.BytesIO()
    with zipfile.ZipFile(out, "w", zipfile.ZIP_DEFLATED) as archive:
        archive.writestr("word/document.xml", "0" * 5000)
    with pytest.raises(OfficeReadError, match="too large"):
        office_text(out.getvalue(), DOCX)


@pytest.mark.parametrize("mime_type", [DOCX, XLSX, PPTX])
def test_garbage_is_a_read_error(mime_type: str) -> None:
    with pytest.raises(OfficeReadError):
        office_text(b"not an office file at all", mime_type)


def test_a_valid_zip_that_is_not_the_claimed_type_is_a_read_error() -> None:
    with pytest.raises(OfficeReadError):
        office_text(_xlsx(), DOCX)


# The message and retrieve_file: text in, and never an exception out


def _b64(data: bytes) -> str:
    import base64

    return base64.b64encode(data).decode()


def test_an_attached_spreadsheet_reaches_the_model_as_text() -> None:
    from src.agent.message_content import build_message_content

    file = {"name": "budget.xlsx", "type": XLSX, "data": _b64(_xlsx()), "history_file_id": "m1:0"}
    blocks = build_message_content("what does it cost?", [file])
    assert isinstance(blocks, list)
    texts = [b["text"] for b in blocks if isinstance(b, dict) and b.get("type") == "text"]
    assert any(
        "Content of budget.xlsx (Excel spreadsheet)" in t and "| tent | 120 |" in t for t in texts
    )


def test_a_cut_document_says_where_the_rest_is(monkeypatch: pytest.MonkeyPatch) -> None:
    from src.agent.message_content import build_message_content

    monkeypatch.setattr(Config, "OFFICE_TEXT_MAX_CHARS", 30)
    file = {"name": "plan.docx", "type": DOCX, "data": _b64(_docx()), "history_file_id": "m1:0"}
    blocks = build_message_content("summarise", [file])
    assert isinstance(blocks, list)
    text = next(
        b["text"] for b in blocks if isinstance(b, dict) and "plan.docx" in b.get("text", "")
    )
    assert "truncated" in text
    assert "execute_code(files=['m1:0'])" in text


def test_an_unreadable_document_is_a_notice_with_its_id() -> None:
    from src.agent.message_content import build_message_content

    file = {
        "name": "broken.docx",
        "type": DOCX,
        "data": _b64(b"garbage"),
        "history_file_id": "m1:0",
    }
    blocks = build_message_content("summarise", [file])
    assert isinstance(blocks, list)
    texts = [b["text"] for b in blocks if isinstance(b, dict) and b.get("type") == "text"]
    assert any("broken.docx could not be read as text" in t and "m1:0" in t for t in texts)


def test_retrieve_file_reads_a_presentation_as_text() -> None:
    from unittest.mock import MagicMock, patch

    from src.agent.tools import retrieve_file, set_conversation_context

    message = MagicMock(conversation_id="conv-1", files=[{"name": "deck.pptx", "type": PPTX}])
    message.created_at = datetime.now(UTC)
    store = MagicMock()
    store.get.return_value = (_pptx(), PPTX)
    set_conversation_context("conv-1", "user-1")
    try:
        with (
            patch("src.agent.tools.conversation_files.db") as db,
            patch("src.agent.tools.conversation_files.get_blob_store", return_value=store),
        ):
            db.get_message_by_id.return_value = message
            content = retrieve_file.invoke({"message_id": "m1", "file_index": 0})
    finally:
        set_conversation_context(None, None)
    assert isinstance(content, str)
    assert "## Slide 2" in content
    assert "Notes: Mention the budget" in content


def test_office_files_pass_validation_and_a_disguised_one_does_not() -> None:
    from unittest.mock import patch

    from src.utils.files import validate_files

    allowed = set(Config.DEFAULT_ALLOWED_FILE_TYPES.split(","))
    good = [
        {"name": "a.docx", "type": DOCX, "data": _b64(_docx())},
        {"name": "b.xlsx", "type": XLSX, "data": _b64(_xlsx())},
        {"name": "c.pptx", "type": PPTX, "data": _b64(_pptx())},
    ]
    with patch.object(Config, "ALLOWED_FILE_TYPES", allowed):
        ok, error = validate_files(good)
        assert ok, error
        # A zip is not a PDF, and a PDF is not a Word document
        assert not validate_files(
            [{"name": "x.pdf", "type": "application/pdf", "data": _b64(_docx())}]
        )[0]
        assert not validate_files(
            [{"name": "x.docx", "type": DOCX, "data": _b64(b"%PDF-1.4\n%%EOF")}]
        )[0]


def test_spreadsheets_are_parsed_through_defusedxml() -> None:
    """A spreadsheet is XML the user sent: openpyxl must use defusedxml (entity
    expansion, external entities), which it does only when it is installed."""
    from openpyxl.xml import DEFUSEDXML

    assert DEFUSEDXML is True


# Hostile or odd files (Nov 16 2026 review): a crafted few-KB file stalled a
# worker for minutes, or a 168 KB docx took 103 s and 2.2 GB


def _rezip(data: bytes, part: str, edit: Callable[[str], str]) -> bytes:
    src = zipfile.ZipFile(io.BytesIO(data))
    out = io.BytesIO()
    with zipfile.ZipFile(out, "w", zipfile.ZIP_DEFLATED) as dst:
        for info in src.infolist():
            body = src.read(info.filename)
            if info.filename == part:
                body = edit(body.decode()).encode()
            dst.writestr(info.filename, body)
    return out.getvalue()


def test_a_sheet_declaring_the_whole_grid_finishes_quickly() -> None:
    book = openpyxl.Workbook()
    sheet = book.active
    assert sheet is not None
    sheet["A1"] = "start"
    sheet["XFD1048576"] = "far corner"
    out = io.BytesIO()
    book.save(out)

    started = time.monotonic()
    result = office_text(out.getvalue(), XLSX)

    assert time.monotonic() - started < 10
    assert "start" in result.text
    assert result.truncated is True  # columns past the cap are left out


def test_a_sheet_declaring_too_small_a_range_keeps_every_row() -> None:
    book = openpyxl.Workbook()
    sheet = book.active
    assert sheet is not None
    for n in range(1, 51):
        sheet.append([f"row {n}"])
    out = io.BytesIO()
    book.save(out)
    data = _rezip(
        out.getvalue(),
        "xl/worksheets/sheet1.xml",
        lambda xml: re.sub(r'<dimension ref="[^"]*"', '<dimension ref="A1:A1"', xml),
    )
    assert "| row 50 |" in office_text(data, XLSX).text


def test_too_much_document_xml_is_refused(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(Config, "OFFICE_MAX_XML_BYTES", 1000)
    with pytest.raises(OfficeReadError, match="too large"):
        office_text(_docx(), DOCX)


def test_a_conversion_that_runs_too_long_is_stopped(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(Config, "OFFICE_TEXT_TIMEOUT_SECONDS", 0.01)
    with pytest.raises(OfficeReadError, match="too long"):
        office_text(_docx(), DOCX)


def test_unknown_bytes_do_not_pass_as_a_voice_memo_or_a_document() -> None:
    from unittest.mock import patch

    from src.utils.files import validate_files

    noise = _b64(b"\x00\x13\x7f" * 700)  # libmagic: application/octet-stream
    allowed = set(Config.DEFAULT_ALLOWED_FILE_TYPES.split(","))
    with patch.object(Config, "ALLOWED_FILE_TYPES", allowed):
        assert not validate_files([{"name": "m.m4a", "type": "audio/x-m4a", "data": noise}])[0]
        assert not validate_files([{"name": "d.docx", "type": DOCX, "data": noise}])[0]
