# doc2docx

`doc2docx` is a specification-driven, pure-Python converter for Microsoft Word
97–2003 binary `.doc` files. It does not invoke Microsoft Word, LibreOffice,
COM, Java, or an external conversion executable.

The current M0–M4a implementation supports unencrypted CFB/OLE Word documents,
the `0Table`/`1Table` selection mechanism, CLX piece tables, compressed and
UTF-16LE text pieces, and the main document story. It reads CHPX/PAPX FKPs and
preserves a useful first set of direct character and paragraph properties. It
also reads the SttbfFfn font table, emits DOCX font definitions, converts
paragraph/character styles with `basedOn` inheritance, resolves style-relative
toggles, and applies simple and complex piece-level PRMs in specification order.
It reconstructs non-nested tables from DOC cell/row markers and preserves their
column grid, preferred cell widths, basic merges, alignment, row sizing, and
Word 97 table borders.

## Usage

```console
python -m pip install .
doc2docx input.doc
doc2docx input.doc -o output.docx --report report.json
doc2docx inspect input.doc --json
```

Python API:

```python
from doc2docx import convert

result = convert("input.doc", "output.docx")
print(result.report.to_dict())
```

M4a currently preserves bold, italic, strike, double strike, capitalization,
hidden text, underline, text color, highlight, font size, vertical alignment,
paragraph justification, indents, spacing, line spacing, and keep/page-break
flags, font names, paragraph/character style references, and style inheritance.
Nested tables, advanced table styles and shading, numbering styles, secondary
stories, images, live fields, embedded objects, and encrypted documents are
intentionally deferred to later iterations. Unsupported or lossy content is
reported rather than silently treated as fully converted.

## Tests

The test suite uses only the Python standard library:

```console
PYTHONPATH=src python -m unittest discover -v
```

It includes constructed CFB version 3/version 4 files, regular and mini streams,
both Table stream variants, mixed compressed/UTF-16 text pieces, UTF-16 surrogate
pair coordinates, CHPX/PAPX and piece-level PRM formatting, font/style table
parsing, table reconstruction and grids, malformed input checks, CLI coverage,
and end-to-end DOCX package validation.
