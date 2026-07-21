# Changelog

This file records milestone-level changes. The README describes the converter's
current capabilities without release-by-release notes.

## Unreleased

- Continue expanding MS-DOC compatibility with specification-backed parsers,
  focused tests, and real Word 97 sample rendering.

## 0.26.0 - 2026-07-22 (M11b)

- Preserve declared `NOTEREF` fields when their bookmark target exists, and
  normalize the legacy `FTNREF` spelling to the WordprocessingML field name.
- Preserve `SEQ` fields with a sequence identifier and `STYLEREF` fields whose
  case-insensitive style target exists in the parsed style sheet; broken local
  fields remain cached display text with targeted diagnostics.
- Share emitted bookmark and parsed style-name context with footnotes,
  endnotes, comments, headers, footers, and both textbox stories so fields are
  evaluated consistently outside the main story.
- Keep `LISTNUM` cached until its legacy list-name table can be matched safely
  to native list definitions instead of activating an ambiguous field.
- Validate with 138 focused tests and a real Word 97 DOC containing `NOTEREF`,
  `SEQ`, and `STYLEREF`, followed by package inspection and rendered visual
  verification.

## 0.25.0 - 2026-07-22 (M11a)

- Parse standard bookmark names and ranges from `SttbfBkmk`, `Plcfbkf`, and
  `Plcfbkl`, including overlapping, zero-length, and table-column bookmarks.
- Emit paired WordprocessingML bookmark markers in the main story and preserve
  declared `REF` and `PAGEREF` fields as live fields only when their target
  bookmark is present; broken references remain cached display text.
- Validate string-table bounds, parallel entry counts, bookmark CPs, FBKF end
  indexes, BKC flags, table-column ranges, and both specification and common
  document-end terminal-CP variants.
- Move field-instruction/private-result bookmark boundaries to a safe field
  edge when necessary, and remove non-XML controls from field instructions so
  output packages remain valid while reporting the approximation.
- Validate with malformed, overlapping, point, column, private-field, and
  end-to-end CFB fixtures plus a real Word 97 DOC containing a bookmark and
  live REF field, followed by rendered visual verification.

## 0.24.0 - 2026-07-22 (M10b)

- Validate the MS-DOC `Plcfld`/`Fld` structures for the main, header/footer,
  footnote, endnote, comment, and textbox stories, including bounded CP ranges,
  field-character matching, nesting, separators, field types, and end flags.
- Preserve locked and dirty/edited field states in WordprocessingML while
  preventing field-like control characters absent from `Plcfld` from becoming
  live output fields.
- Suppress private field results, retain cached text for unsupported or active
  fields, and report missing `sprmCFSpec`, unknown field types, omitted nested
  fields, and legacy display flags that cannot be represented directly.
- Validate with malformed and nested constructed cases plus a real Word 97 DOC
  containing six declared fields and eighteen field characters, with a clean
  conversion report and rendered output.

## 0.23.0 - 2026-07-22 (M10a)

- Preserve common date/time, document metadata, pagination, section, filename,
  file-size, and document-statistic fields as live WordprocessingML fields,
  including fields without a cached-result separator.
- Keep DDE, external-include, link/OLE-control, macro-button, print, and add-in
  fields as cached display text, with an explicit safety diagnostic instead of
  activating them in the output package.
- Parse the OLE `\x05SummaryInformation` property set with bounded offsets,
  code-page-aware strings, typed FILETIME values, and recoverable diagnostics.
- Emit `docProps/core.xml`, its package relationship and content type so title,
  author, subject, keywords, comments, revision, and core timestamps survive
  conversion and continue to back live metadata fields.
- Validate with constructed malformed/property-type cases and a real Word 97
  DOC containing DATE, TIME, NUMPAGES, NUMWORDS, TITLE, and FILENAME fields.

## 0.22.0 - 2026-07-22 (M9a)

- Parse native `PlfLst`/`LSTF`/`LVL` list definitions and
  `PlfLfo`/`LFOData`/`LFOLVL` instances, including start-at and complete level
  overrides with bounded variable-length records.
- Preserve paragraph and style `iLfo`/`iLvl` bindings, skipped list paragraphs,
  negative iLfo variants, multilevel label text, list indents, label fonts,
  suffixes, justification, legal numbering, and restart behavior.
- Emit native `word/numbering.xml`, package relationships, content types, and
  `w:numPr` bindings using the MS-OSHARED numbering-format mapping.
- Validate numbered, bulleted, and true multilevel lists with real Word 97 DOC
  rendering, plus constructed override and malformed-boundary tests.

## 0.21.0 - 2026-07-22 (M8e)

- Decode TIFF, EMF, and WMF OfficeArt BLIPs in inline and floating picture
  paths, including compressed and uncompressed metafile payloads.
- Enforce declared compressed/uncompressed sizes, supported compression flags,
  the metafile filter byte, format signatures, and a bounded expansion limit.
- Preserve EMF/WMF media as native DOCX image parts; validate with a real Word
  97 DOC containing both formats and rendered output. LibreOffice normalized
  the TIFF sample to PNG, while native TIFF BLIPs are covered by constructed
  record tests.

## 0.20.0 - 2026-07-22 (M8d)

- Recover inline PNG, JPEG, and DIB pictures from header/footer stories through
  their `U+0001` anchors, CHPX picture properties, and the DOC `Data` stream.
- Inject recovered pictures into the correct header/footer story and reuse
  part-scoped image relationships.
- Validate the path with unit coverage and a real header-image DOC round trip.

## 0.19.0 - 2026-07-22 (M8c)

- Recover floating raster pictures from `PlcSpaHdr` and OfficeArt while
  excluding textbox shapes that share the same anchor table.
- Scope image relationships to `document.xml`, `headerN.xml`, or `footerN.xml`
  according to the part that references each picture.
- Validate header floating pictures with a real Word 97 DOC and rendered output.

## 0.18.0 - 2026-07-22 (M8b)

- Recover main-story floating raster pictures through `PlcSpaMom`, FOPT `pib`,
  the global BLIP store, and delayed BLIP data in `WordDocument`.
- Emit positioned DrawingML anchors with basic relative positioning, wrapping,
  behind-text, and lock flags.

## 0.17.0 - 2026-07-22 (M8a)

- Recover main-story inline PNG, JPEG, and DIB pictures from PICF/OfficeArt
  records in the DOC `Data` stream.
- Emit deterministic media parts, image relationships, and DrawingML inline
  pictures without external conversion tools.
