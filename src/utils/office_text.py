"""Office documents as text for the chat model (Nov 16 2026).

Gemini takes no docx, xlsx or pptx, so the agent reads their text instead:
Word as headings, paragraphs and tables, Excel as one table per sheet
(cached values, or the formula where a script wrote the file and nothing
computed it), PowerPoint as each slide's text and notes. Layout is lost; the
original still goes to the code sandbox for edits.

The file is a zip archive the user sent, and a crafted one of a few KB
stalled a worker for minutes (a sheet declaring the whole grid; a docx of
millions of empty paragraphs took 103 s and 2.2 GB - Nov 16 2026 review). So:
- the archive's unpacked size and its XML's size are capped before parsing;
- parsing runs in a child process (`python -m src.utils.office_text`) with a
  time limit and, on Linux, an address-space limit: whatever a file does
  costs that process, never the worker;
- Excel is read by its real extent (not the declared one), at most
  XLSX_MAX_COLUMNS columns and XLSX_MAX_ROWS_SCANNED rows per sheet;
- openpyxl parses through defusedxml (installed for it), and the text stops
  at OFFICE_TEXT_MAX_CHARS instead of being built whole.
"""

from __future__ import annotations

import io
import json
import subprocess
import sys
import zipfile
from collections.abc import Callable, Iterable
from dataclasses import dataclass
from datetime import date, datetime

import docx
import openpyxl
from docx.table import Table
from docx.text.paragraph import Paragraph
from openpyxl.worksheet._read_only import ReadOnlyWorksheet
from pptx import Presentation

from src.config import Config

DOCX = "application/vnd.openxmlformats-officedocument.wordprocessingml.document"
XLSX = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
PPTX = "application/vnd.openxmlformats-officedocument.presentationml.presentation"

# What each type is called in the message and the history
OFFICE_KINDS = {DOCX: "Word document", XLSX: "Excel spreadsheet", PPTX: "PowerPoint presentation"}


# Excel: columns read per row, and rows scanned per sheet (empty ones count)
XLSX_MAX_COLUMNS = 200
XLSX_MAX_ROWS_SCANNED = 100_000


class OfficeReadError(Exception):
    """The file cannot be read as text; the message says why, for the agent."""


@dataclass(frozen=True)
class OfficeText:
    text: str
    truncated: bool


class _CapReachedError(Exception):
    """The text reached its cap: stop reading."""


class _Lines:
    """Collects lines up to a character cap."""

    def __init__(self, max_chars: int) -> None:
        self._parts: list[str] = []
        self._left = max_chars
        # Something was left out before the cap (columns, rows)
        self.cut = False

    def add(self, line: str) -> None:
        piece = line + "\n"
        if len(piece) > self._left:
            self._parts.append(piece[: self._left])
            self._left = 0
            raise _CapReachedError
        self._parts.append(piece)
        self._left -= len(piece)

    def text(self) -> str:
        return "".join(self._parts).rstrip("\n")


def _row(cells: Iterable[str]) -> str:
    return "| " + " | ".join(c.replace("\n", " ").replace("|", "/") for c in cells) + " |"


def _read_docx(data: io.BytesIO, out: _Lines) -> None:

    document = docx.Document(data)
    # Paragraphs and tables in reading order (document.paragraphs skips tables)
    for child in document.element.body.iterchildren():
        tag = child.tag.rsplit("}", 1)[-1]
        if tag == "p":
            _docx_paragraph(Paragraph(child, document), out)
        elif tag == "tbl":
            for row in Table(child, document).rows:
                out.add(_row(cell.text for cell in row.cells))
            out.add("")


def _docx_paragraph(paragraph: Paragraph, out: _Lines) -> None:
    text = paragraph.text.strip()
    if not text:
        return
    style = getattr(paragraph.style, "name", "") or ""
    if style == "Title":
        out.add(f"# {text}")
    elif style.startswith("Heading ") and style[8:].isdigit():
        out.add(f"{'#' * min(int(style[8:]), 6)} {text}")
    else:
        out.add(text)


def _cell(value: object) -> str:
    if value is None:
        return ""
    if isinstance(value, datetime | date):
        return value.isoformat()
    if isinstance(value, float) and value.is_integer():
        return str(int(value))
    return str(value)


def _read_xlsx(data: io.BytesIO, out: _Lines) -> None:
    values = openpyxl.load_workbook(data, read_only=True, data_only=True)
    data.seek(0)
    formulas = openpyxl.load_workbook(data, read_only=True, data_only=False)
    for name in values.sheetnames:
        out.add(f"## Sheet: {name}")
        _xlsx_sheet(values[name], formulas[name], out)
        out.add("")


def _xlsx_sheet(values: ReadOnlyWorksheet, formulas: ReadOnlyWorksheet, out: _Lines) -> None:
    # The declared range is the file's claim: too big stalls, too small drops rows
    values.reset_dimensions()
    formulas.reset_dimensions()
    rows = zip(
        values.iter_rows(values_only=True), formulas.iter_rows(values_only=True), strict=False
    )
    for scanned, (cached, written) in enumerate(rows):
        if scanned >= XLSX_MAX_ROWS_SCANNED:
            out.cut = True
            return
        if any(c is not None for c in cached[XLSX_MAX_COLUMNS:]):
            out.cut = True
        cached, written = cached[:XLSX_MAX_COLUMNS], written[:XLSX_MAX_COLUMNS]
        # A cell nothing computed has no cached value: show its formula
        padded = (*written, *[None] * (len(cached) - len(written)))
        cells = [_cell(c if c is not None else w) for c, w in zip(cached, padded, strict=False)]
        while cells and not cells[-1]:
            cells.pop()
        if cells:
            out.add(_row(cells))


def _read_pptx(data: io.BytesIO, out: _Lines) -> None:

    deck = Presentation(data)
    for number, slide in enumerate(deck.slides, start=1):
        out.add(f"## Slide {number}")
        for shape in slide.shapes:
            if getattr(shape, "has_text_frame", False) and shape.text_frame.text.strip():
                out.add(shape.text_frame.text.strip())
            elif getattr(shape, "has_table", False):
                for row in shape.table.rows:
                    out.add(_row(cell.text for cell in row.cells))
        if slide.has_notes_slide:
            notes = slide.notes_slide.notes_text_frame
            if notes is not None and notes.text.strip():
                out.add(f"Notes: {notes.text.strip()}")
        out.add("")


_READERS: dict[str, Callable[[io.BytesIO, _Lines], None]] = {
    DOCX: _read_docx,
    XLSX: _read_xlsx,
    PPTX: _read_pptx,
}


def _check_archive(data: bytes, max_xml_bytes: int, max_total_bytes: int) -> None:
    """A zip whose unpacked size, and its XML's, are within the caps (before parsing)."""
    try:
        with zipfile.ZipFile(io.BytesIO(data)) as archive:
            # zipfile never reads past an entry's declared size, so the
            # declared sizes bound what the parsers can unpack
            infos = archive.infolist()
    except zipfile.BadZipFile as e:
        raise OfficeReadError("not an Office file (no zip archive)") from e
    unpacked = sum(info.file_size for info in infos)
    xml = sum(info.file_size for info in infos if info.filename.endswith((".xml", ".rels")))
    if unpacked > max_total_bytes or xml > max_xml_bytes:
        raise OfficeReadError(f"too large when unpacked ({max(unpacked, xml) // 1_000_000} MB)")


def _extract(
    data: bytes, mime_type: str, max_chars: int, max_xml: int, max_total: int
) -> OfficeText:
    """Parse in this process (the child's side of office_text)."""
    reader = _READERS[mime_type]
    _check_archive(data, max_xml, max_total)
    out = _Lines(max_chars)
    truncated = False
    try:
        reader(io.BytesIO(data), out)
    except _CapReachedError:
        truncated = True
    except Exception as e:  # a parser's any failure is the file's, not the turn's
        raise OfficeReadError(f"not a readable {OFFICE_KINDS[mime_type]}") from e
    return OfficeText(out.text(), truncated or out.cut)


def office_text(data: bytes, mime_type: str) -> OfficeText:
    """The document's text, at most OFFICE_TEXT_MAX_CHARS; OfficeReadError if unreadable.

    Parsed in a child process under OFFICE_TEXT_TIMEOUT_SECONDS and
    OFFICE_MAX_MEMORY_BYTES, so a hostile file cannot hold a worker.
    """
    if mime_type not in OFFICE_KINDS:
        raise OfficeReadError(f"not an Office type: {mime_type}")
    limits = [
        Config.OFFICE_TEXT_MAX_CHARS,
        Config.OFFICE_MAX_XML_BYTES,
        Config.OFFICE_MAX_UNCOMPRESSED_BYTES,
        Config.OFFICE_MAX_MEMORY_BYTES,
    ]
    command = [sys.executable, "-m", "src.utils.office_text", mime_type, *map(str, limits)]
    try:
        done = subprocess.run(  # noqa: S603 - our own interpreter and module, fixed arguments
            command,
            input=data,
            capture_output=True,
            timeout=Config.OFFICE_TEXT_TIMEOUT_SECONDS,
            cwd=Config.BASE_DIR,
            check=False,
        )
    except subprocess.TimeoutExpired as e:
        raise OfficeReadError(
            f"took too long to read (over {Config.OFFICE_TEXT_TIMEOUT_SECONDS} s)"
        ) from e
    try:
        result = json.loads(done.stdout)
    except ValueError as e:
        # Killed (the memory limit) or crashed before it could answer
        raise OfficeReadError("too large or complex to read") from e
    if "error" in result:
        raise OfficeReadError(result["error"])
    return OfficeText(result["text"], bool(result["truncated"]))


def _limit_memory(max_bytes: int) -> None:
    """Cap this process's address space (Linux; macOS ignores or refuses it)."""
    try:
        import resource  # noqa: PLC0415 - POSIX only, and only the child needs it

        resource.setrlimit(resource.RLIMIT_AS, (max_bytes, max_bytes))
    except ImportError, ValueError, OSError:
        pass


def _main(argv: list[str]) -> None:
    mime_type, max_chars, max_xml, max_total, max_memory = argv
    _limit_memory(int(max_memory))
    data = sys.stdin.buffer.read()
    try:
        result = _extract(data, mime_type, int(max_chars), int(max_xml), int(max_total))
        answer: dict[str, object] = {"text": result.text, "truncated": result.truncated}
    except OfficeReadError as e:
        answer = {"error": str(e)}
    sys.stdout.write(json.dumps(answer))


if __name__ == "__main__":
    _main(sys.argv[1:])
