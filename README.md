# doc2docx

`doc2docx` is a specification-driven, pure-Python converter for Microsoft Word
97–2003 binary `.doc` files. It does not invoke Microsoft Word, LibreOffice,
COM, Java, or an external conversion executable.

The current M0–M2 implementation supports unencrypted CFB/OLE Word documents,
the `0Table`/`1Table` selection mechanism, CLX piece tables, compressed and
UTF-16LE text pieces, and the main document story. It writes a minimal,
standards-based WordprocessingML `.docx` package.

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

Formatting, tables, secondary stories, images, fields, embedded objects, and
encrypted documents are intentionally deferred to later milestones. Unsupported
or lossy content is reported rather than silently treated as fully converted.

## Tests

The test suite uses only the Python standard library:

```console
PYTHONPATH=src python -m unittest discover -v
```

It includes constructed CFB version 3/version 4 files, regular and mini streams,
both Table stream variants, mixed compressed/UTF-16 text pieces, malformed input
checks, CLI coverage, and end-to-end DOCX package validation.
