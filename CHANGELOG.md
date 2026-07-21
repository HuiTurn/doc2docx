# Changelog

This file records milestone-level changes. The README describes the converter's
current capabilities without release-by-release notes.

## Unreleased

## 0.30.0 - 2026-07-22 (M14a-M14b)

- Preserve character-formatting, text-insertion, and paragraph-formatting
  revision save identifiers as native WordprocessingML attributes.
- Honor field-hidden formatting through native field-code semantics, and
  preserve fixed/automatic table layout and table style look flags.
- Follow the MS-DOC rule that the final `Plcfld` CP is undefined, and reconcile
  stale `fHasSep` flags with the validated field-character sequence.
- Safely omit bounded zero-content header and annotation-bookmark PLC remnants,
  accept the observed annotation terminal-CP variant, and preserve comment text
  when a legacy writer places its annotation marker after visible content.
- Validate with 154 focused tests and a 42-file real-DOC regression batch: 40
  Word 97–2003 files convert successfully, including five previously rejected
  structures, while the remaining two are Word 6/95 files outside the declared
  input scope. Render a complex multi-story sample containing headers, text
  boxes, footnotes, endnotes, comments, and fields for visual verification.

## 0.29.0 - 2026-07-22 (M13a-M13b)

- Preserve signed character spacing from `sprmCDxaSpace` in direct and style
  formatting as native WordprocessingML character pitch adjustments.
- Preserve contextual paragraph spacing and automatic spacing before/after,
  and serialize paragraph properties in WordprocessingML schema order.
- Preserve evenly spaced section column counts and spacing, section revision
  save identifiers, and signed preferred table indents from direct and style
  formatting.
- Validate with 143 focused tests and a 42-file real-DOC regression batch: the
  high-frequency style-character and style-paragraph warnings fell from nine
  files each to one and zero, table-style warnings fell from five to zero, and
  section warnings fell from five to one implementation-dependent property.
- Inspect and render real floating-picture and legacy sample documents after
  package validation to confirm that the added layout properties do not
  regress visible content.

## 0.28.0 - 2026-07-22 (M12a-M12b)

- Preserve paragraph and paragraph-style controls for line-number suppression,
  automatic-hyphenation suppression, and bidirectional layout.
- Parse section page-number formats, footnote and endnote number formats and
  restart rules, section bidirectional layout, and representable MSOTXFL text
  directions, then emit them in schema order in `w:sectPr`.
- Share the specification-backed MSONFC mapping between native list levels and
  section numbering controls, while keeping unrepresentable section text-flow
  values explicitly diagnosed.
- Expose section numbering, bidirectional, and vertical-text counts in the
  conversion report.
- Validate with 142 focused tests and a real Word 97 DOC whose previously
  unsupported paragraph, style, and section modifiers now convert without
  compatibility warnings, followed by package and rendered visual checks.

## 0.27.0 - 2026-07-22 (M11c)

- Parse the extended UTF-16 `SttbListNames` table parallel to `PlfLst`, with
  strict bounds, header, length, uniqueness, and trailing-data validation.
- Attach retained names to their native abstract numbering definitions and
  emit them as WordprocessingML `w:name` elements.
- Preserve declared `LISTNUM` fields as live fields only when their
  case-insensitive name resolves to an emitted list definition; missing,
  unnamed, or renamed targets remain cached text with a targeted diagnostic.
- Share named-list context across main, note, comment, header/footer, and
  textbox stories, and expose the source table and named-list count through
  inspection and conversion statistics.
- Validate with 140 focused tests plus matching and renamed real Word 97 DOC
  cases; the matching case retained both native paragraph numbering and a live
  inline `LISTNUM` field through rendered visual verification.

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
