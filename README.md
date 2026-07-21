# doc2docx

`doc2docx` is a specification-driven, pure-Python converter for Microsoft Word
97–2003 binary `.doc` files. It does not invoke Microsoft Word, LibreOffice,
COM, Java, or an external conversion executable.

The current M0–M8c implementation supports unencrypted CFB/OLE Word documents,
the `0Table`/`1Table` selection mechanism, CLX piece tables, compressed and
UTF-16LE text pieces, and the main document story. It reads CHPX/PAPX FKPs and
preserves a useful first set of direct character and paragraph properties. It
also reads the SttbfFfn font table, emits DOCX font definitions, converts
paragraph/character styles with `basedOn` inheritance, resolves style-relative
toggles, parses unconditional table-style TAPX/PAPX/CHPX properties, preserves
`sprmTIstd` as native DOCX table-style references, and applies simple and complex
piece-level PRMs in specification order.
It reconstructs tables from DOC cell/row markers, including nested tables, and
preserves their column grid, explicit table and cell widths, basic merges,
alignment, row sizing, Word 97 and modern borders, per-cell border colors,
shading, and default or range-specific cell margins. It also follows main-story
`PlcfSed` records through `Sed.fcSepx` to
each `Sepx.grpprl`, reconstructing single or multiple sections. Section-break
types, paper size, portrait/landscape orientation, page margins, header/footer
distance, and gutter width are emitted as WordprocessingML section properties.
It parses `PlcfHdd`, removes each story's guard paragraph, preserves the six
default/even/first header and footer positions per section, and retains empty-story
inheritance. Header/footer parts, relationships, first-page rules, and the DOP
facing-pages setting are written as native DOCX package parts. Header textbox
stories are resolved through `PlcfHdrtxbxTxt`, `PlcfTxbxHdrBkd`, and
`PlcSpaHdr`; their shape rectangle, relative positioning, wrapping, and anchor
flags are emitted as compatible VML textboxes. The corresponding `DggInfo`
OfficeArt drawing is matched by shape id so solid fill, opacity, line color,
line opacity/width, and textbox insets can also be retained. `PAGE`, `NUMPAGES`, and
`SECTIONPAGES` are preserved as live WordprocessingML fields with their cached
display results. East Asian section document grids, grid-aware paragraph
controls, script-specific font hints, language/proofing metadata, complex-script
font size and emphasis, and Word's table-grid line-height compatibility setting
are also carried into the DOCX package. Paragraph-mark formatting, spacing in
hundredths of a line, and `sprmCSymbol` characters are preserved as native
WordprocessingML run and symbol elements. Paragraph borders, outline levels, and
custom tab additions/deletions are retained as native paragraph properties.
Automatic footnotes and endnotes are resolved through their reference/text
PLCs, linked to main-story reference CPs, and emitted as native
`footnotes.xml`/`endnotes.xml` content with package relationships and automatic
reference marks. Malformed PLC layouts, invalid automatic reference characters,
and missing `sprmCFSpec` formatting are rejected instead of being guessed.
Legacy comments are resolved through `PlcfandRef`/`PlcfandTxt`, author XSTs,
and annotation bookmark tables. Ordinary range and insertion-point comments are
emitted as native main-story anchors plus `comments.xml`, preserving author
names and initials.
Main-story textboxes are likewise resolved through `PlcSpaMom`,
`PlcftxbxTxt`, and `PlcfTxbxBkd`; their text, basic fields, position, wrapping,
anchor flags, and OfficeArt appearance use the same validated floating-shape
pipeline as header/footer textboxes.
Main-story inline picture characters are resolved through `sprmCFSpec`,
`sprmCPicLocation`, the `Data` stream, 68-byte `PICF` headers, and bounded
OfficeArt inline-shape/FBSE records. Embedded PNG, JPEG, and DIB BLIPs are
written as deterministic `word/media` parts with native DrawingML inline
picture markup; DIB payloads receive a pure-Python BMP file header. Reused
picture data receives unique drawing identifiers, malformed records and
non-raster BLIP types remain explicit diagnostics, and display dimensions are
preserved from `PICMID` goal sizes and scaling ratios. Empty font-table slots
seen in LibreOffice Word 97 exports are retained by index with a repair
diagnostic rather than shifting every subsequent font reference.
Main-story floating PNG/JPEG/DIB pictures are associated by shape id across
`PlcSpaMom`, OfficeArt FOPT `pib`, the global BLIP store, and its
`WordDocument` delay stream. Their page/column/margin or paragraph-relative
position, size, behind-text/locked flags, and square/top-bottom/no-wrap mode
are emitted as DrawingML `wp:anchor` objects. Complex inline `pib` BLIPs are
also accepted; tight and through wrap polygons currently fall back to square
wrapping with an explicit diagnostic.
The same `PlcSpaHdr` and OfficeArt path now restores floating raster pictures
from header/footer stories. Image relationships are scoped to the XML part that
uses them (`document.xml`, `headerN.xml`, or `footerN.xml`) while media payloads
remain shared under `word/media`.

## Usage

```console
python -m pip install msdoc2docx
doc2docx input.doc
doc2docx input.doc -o output.docx --report report.json
doc2docx inspect input.doc --json
```

To install from a local source checkout instead, run `python -m pip install .`.

Python API:

```python
from doc2docx import convert

result = convert("input.doc", "output.docx")
print(result.report.to_dict())
```

M8c currently preserves bold, italic, strike, double strike, capitalization,
hidden text, underline, text color, highlight, font size, vertical alignment,
paragraph justification, indents, spacing, line spacing, and keep/page-break
flags, font names, paragraph/character style references, style inheritance,
basic section/page layout, ordinary paragraph/table content in headers and
footers, positioned header/footer and main-story textboxes, and basic dynamic
page-number fields. It additionally distinguishes Latin/East Asian/complex-script run
properties and preserves East Asian document-grid pagination controls. Paragraph
borders, outline levels, and custom tab stops are preserved. Basic unconditional
table styles are emitted as `w:style` definitions and selected by `w:tblStyle`;
conditional cell/band/corner variants remain deferred.
Custom footnote and endnote symbols currently fall back to automatic numbering
with an explicit diagnostic. Conditional table styles, newer color-based table
shading, cell spacing,
numbering styles, multi-column layout, page-number settings, header/footer
non-picture/non-textbox shapes and advanced OfficeArt effects, other
secondary stories, vector/metafile and TIFF pictures, inline pictures outside
the main story, non-rectangular picture wrap polygons, fields beyond the supported page-number family,
embedded objects, exact Word 97–2003 table-row pagination in every legacy
compatibility case, and encrypted documents are intentionally deferred to later iterations.
Unsupported or lossy content is reported rather than silently treated as fully
converted.

## Tests

The test suite uses only the Python standard library:

```console
PYTHONPATH=src python -m unittest discover -v
```

It includes constructed CFB version 3/version 4 files, regular and mini streams,
both Table stream variants, mixed compressed/UTF-16 text pieces, UTF-16 surrogate
pair coordinates, CHPX/PAPX and piece-level PRM formatting, font/style table
parsing, nested table reconstruction, grids, cell margins and shading, PlcfSed and
Sepx page-layout parsing, multi-section break placement, PlcfHdd guard and story
mapping, header and main-story textbox/shape/field PLC validation, live PAGE-field output,
basic OfficeArt record/property validation and VML shape styling, header/footer
OPC relationships, automatic footnote/endnote PLC validation and package
output, legacy comment author/range PLC validation and package output, East
Asian document grids and paragraph controls, script-specific language/font
properties, inline PNG/JPEG/DIB PICF/OfficeArt parsing and DrawingML package
output, main/header floating-picture PlcSpa/pib/delayed-BLIP association,
part-scoped image relationships and anchored DrawingML output, malformed
picture and empty-font-slot handling, CLI
coverage, symbol characters, paragraph-mark formatting, paragraph borders and
outline levels, custom tab stops, unconditional table-style inheritance, modern
table borders, explicit table/cell widths, per-cell border colors, and end-to-end
DOCX package validation.
