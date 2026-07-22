# Changelog

This file records milestone-level changes. The README describes the converter's
current capabilities without release-by-release notes.

## Unreleased

### M17a

- Parse `StkListGRLPUPX` numbering-style paragraph properties and emit MS-DOC
  `stkList` definitions as native `w:style type="numbering"` entries.
- Keep unknown style kinds diagnosed while removing the stale deferred warning
  for specification-defined numbering styles.
- Validate with 170 focused tests and the 38-file content-deduplicated real-DOC
  batch: all seven numbering-style documents emit native styles, the deferred
  style-kind diagnostic is eliminated, and all 36 in-scope files still convert.

### M17b

- Preserve section page-number restarts and both legacy 16-bit and modern
  32-bit starting values as native `w:pgNumType w:start` properties.
- Ignore stored start values when page numbering continues, honor later start
  modifiers, and reject values outside the MS-DOC 32-bit bound.
- Validate with 172 focused tests, a real DOC round trip whose live `PAGE`
  field renders as `VII` from an upper-Roman start value of 7, and the unchanged
  38-file regression batch with all 36 in-scope files converting.

### M17c

- Preserve enabled section line numbering, including display interval, starting
  number, text distance, and page/section/continuous restart modes, as native
  `w:lnNumType` properties in schema order.
- Ignore dormant line-number settings when numbering is disabled and enforce
  the MS-DOC interval and distance bounds.
- Preserve the stored zero-based line-number start directly so WordprocessingML
  consumers display the same one-based number as the binary source.
- Validate with 174 focused tests, a real DOC round trip that renders line
  numbers 5, 6, and 7 while retaining the live page field, and the unchanged
  38-file regression batch with all 36 in-scope files converting.

## 0.32.0 - 2026-07-22 (M16a-M16c)

### M16c

- Preserve Word 97 DOP footnote/endnote number formats, starting numbers, and
  restart policies, plus Word 2000+ section-level `sprmSNFtn`/`sprmSNEdn`
  continuous-numbering offsets, as native `w:numFmt`, `w:numStart`, and
  `w:numRestart` properties.
- Enforce the MS-DOC 14-bit numbering range and ignore section offsets when the
  corresponding numbering mode restarts, as required by the binary format.
- Retain DOP starting values as an interoperability fallback for newer DOC
  versions whose writers omit the equivalent section offset SPRM.
- Validate with 169 focused tests and the content-deduplicated 38-file real-DOC
  batch: all 36 in-scope files convert without unsupported-property warnings.
  A non-default lower-letter footnote starting at 7 survives a
  DOCX-to-DOC-to-DOCX round trip and renders with the expected `g` reference.

### M16b

- Preserve legacy DOP footnote placement for Word 97 documents, section-level
  `sprmSFpc` placement overrides, and document-wide endnote placement as native
  `w:footnotePr`/`w:endnotePr` position properties.
- Preserve `sprmSFEndnote` section suppression as native `w:noEndnote`, and
  report how many sections carry note-placement behavior.
- Validate invalid DOP/Sepx enumeration values without guessing, while allowing
  newer DOC versions to use their section-level footnote defaults.
- Validate with 164 focused tests and the content-deduplicated 38-file real-DOC
  batch: all 36 in-scope Word 97–2003 files convert, both note samples reopen
  and render, and the only two rejected files remain Word 6/95 inputs.

### M16a

- Preserve all six `PlcfHdd` footnote/endnote separator, continuation
  separator, and continuation-notice stories instead of discarding them.
- Map special MS-DOC U+0003/U+0004 line characters to native
  `w:separator`/`w:continuationSeparator` run content while retaining custom
  text, paragraph formatting, and story structure in the note parts.
- Create footnote or endnote package parts when custom separator stories exist
  even if the document has no note references, and expose the preserved story
  count in conversion statistics.
- Validate with 162 focused tests and a real Word 97 Unicode header/footer
  sample containing four default separator stories; both note parts reopen and
  the two-page document renders without layout or Unicode regressions.

## 0.31.0 - 2026-07-22 (M15a-M15c)

### M15c

- Repair the observed unassigned East Asian language ID `0x00FF` to the BCP 47
  no-linguistic-content tag `zxx`, while retaining targeted style/direct
  diagnostics instead of silently treating the value as a concrete language.
- Preserve Word's internal `0x001E` nonbreaking hyphen and `0x001F` optional
  hyphen as native `w:noBreakHyphen` and `w:softHyphen` run content.
- Validate with 161 focused tests and the 42-file regression batch. All 40
  in-scope files convert with no remaining `UNSUPPORTED_*` diagnostics; the
  two rejected inputs remain Word 6/95 files outside the declared scope. Reopen
  the repaired language/hyphen sample and export it to PDF successfully.

### M15b

- Preserve MS-DOC paragraph-frame anchors and wrapping, regular and margin
  drop caps with their line count, and legacy paragraph shading as native
  `w:framePr` and `w:shd` properties in schema order.
- Validate with 158 focused tests and the 42-file regression batch. The two
  frame-heavy Word 97 samples no longer emit unsupported paragraph-property
  warnings, and rendered output now places the three-line margin drop cap next
  to its wrapped paragraph instead of leaving an oversized centered letter.

### M15a

- Follow `sprmPTableProps` and `sprmPHugePapx` references into bounded
  `PrcData` structures in the Data Stream, including cycle detection and the
  MS-DOC rule that processing an indirection ends the containing property list.
- Preserve table-cell insertion and column widths, modern raw cell shading,
  table-formatting revision IDs, and printer-independent paper sizing while
  safely ignoring the implementation-specific paper-selection tie breaker.
- Preserve character outline, shadow, emboss, imprint, emphasis-mark, and
  horizontal-scale properties in native WordprocessingML.
- Validate with 156 focused tests and a 42-file real-DOC regression batch: all
  40 Word 97–2003 files still convert, the two remaining files are Word 6/95,
  and the targeted table and footnote samples no longer report their previous
  unsupported-property warnings. Reopen and render the generated packages to
  verify the four-column header table and character-formatting paths.

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
