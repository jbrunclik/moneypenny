---
name: pdf-documents
description: PDF files via execute_code, including non-ASCII text (Czech/Polish diacritics) with the pre-installed DejaVu fonts. Load BEFORE writing code that creates a PDF.
---
# PDF documents (execute_code)

- **For PDFs with non-ASCII text (accents, diacritics, Czech/Polish/etc.)**: Use fpdf2 with the pre-installed DejaVu fonts (regular + bold are at the path below). Do NOT probe the filesystem for fonts - the paths are fixed; write one complete script:
  ```python
  from fpdf import FPDF
  pdf = FPDF()
  pdf.add_page()
  pdf.add_font('DejaVu', '', '/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf')
  pdf.add_font('DejaVu', 'B', '/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf')
  pdf.set_font('DejaVu', size=12)
  pdf.cell(0, 10, 'Příliš žluťoučký kůň')  # Czech text works!
  pdf.output('/output/document.pdf')
  ```
