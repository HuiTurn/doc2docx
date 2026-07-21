# doc2docx

`doc2docx` is a pure-Python converter from Microsoft Word 97–2003 binary
`.doc` files to modern `.docx` files. The conversion engine follows the
published Microsoft Office binary-format specifications and does not invoke
Microsoft Word, LibreOffice, COM, Java, or another conversion executable.

The project is usable for a growing set of real documents, but it is not yet a
complete implementation of every legacy Word feature. Unsupported or lossy
content is reported explicitly instead of being silently presented as a fully
faithful conversion.

## Highlights

- Reads CFB/OLE Word documents with deterministic, bounded parsers.
- Preserves text, common character and paragraph formatting, fonts, styles,
  native numbered and bulleted lists, tables, page layout, sections, headers,
  and footers.
- Converts footnotes, endnotes, comments, named bookmarks, safe document-local
  reference fields, common date/metadata/page/statistic fields, and positioned
  textboxes to native WordprocessingML structures.
- Preserves core document metadata such as title, author, subject, keywords,
  revision, and creation/modification dates.
- Restores inline and floating PNG, JPEG, BMP/DIB, TIFF, EMF, and WMF pictures
  in the main document and header/footer stories.
- Produces a structured diagnostic report for unsupported, repaired, or
  approximated source features.
- Writes deterministic OPC packages using only the Python standard library at
  runtime.

## Installation

```console
python -m pip install msdoc2docx
```

Python 3.11 or newer is required.

## Command line

Convert beside the input file:

```console
doc2docx input.doc
```

Choose the output path and save a JSON report:

```console
doc2docx input.doc -o output.docx --report report.json
```

Inspect a source file without converting it:

```console
doc2docx inspect input.doc --json
```

## Python API

```python
from doc2docx import convert

result = convert("input.doc", "output.docx")
print(result.report.to_dict())
```

The source document is opened read-only. The destination is written through a
temporary file and atomically replaced after package validation; the converter
will not overwrite the input file.

## Current limitations

Password-protected documents are rejected. Embedded OLE objects, Macintosh
PICT images, advanced drawing effects, non-rectangular wrap polygons, rare list
continuation cases, conditional table styles, uncommon secondary stories, and
many specialized fields remain incomplete. Fields that can execute actions or
access external content are deliberately kept as cached text. Some legacy
layout behavior can only be approximated in WordprocessingML and is called out
in the conversion report.

See [CHANGELOG.md](CHANGELOG.md) for milestone and release details.

## Development

Run the standard-library test suite from a source checkout:

```console
PYTHONPATH=src python -m unittest discover -v
```

Build distributable artifacts with:

```console
python -m build
```

Real-document regression tests may use LibreOffice to create or render test
artifacts, but LibreOffice is not used by the converter itself.

## Specifications

- [MS-DOC: Word Binary File Format](https://learn.microsoft.com/openspecs/office_file_formats/ms-doc/ccd7b486-7881-484c-a137-51170af7cc22)
- [MS-ODRAW: Office Drawing Binary File Format](https://learn.microsoft.com/openspecs/office_file_formats/ms-odraw/)
