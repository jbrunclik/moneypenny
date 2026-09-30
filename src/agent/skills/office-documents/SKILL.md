---
name: office-documents
description: Word, PowerPoint and Excel files (.docx, .pptx, .xlsx) - real structure, styles, tables, slide layouts, Excel formatting and formulas. Load BEFORE writing any code that creates one.
---
# Office documents (execute_code)

- **Office files** - when the user wants Word, PowerPoint or Excel (or an editable document they will send, print or change later), produce the real format, not a PDF or markdown:
  - Word `.docx` -> python-docx (`import docx`); PowerPoint `.pptx` -> python-pptx (`import pptx`); Excel `.xlsx` -> openpyxl (or pandas `to_excel` for plain tables)
  - Use real structure, not manual formatting: built-in heading styles (`doc.add_heading`), list styles (`style='List Bullet'`), real tables (`doc.add_table`, table style `'Light Grid Accent 1'`); slide layouts with title placeholders; one idea per slide, at most ~6 short bullets
  - Excel: bold header row, freeze panes below it (`ws.freeze_panes = 'A2'`), sensible column widths, number formats for money/dates/percent, and write formulas (`'=SUM(B2:B9)'`) where the user would expect them to update
  - Save to `/output/` with a descriptive filename (e.g. `/output/trip-budget.xlsx`) and tell the user what the file contains
