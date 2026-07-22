# Changelog

This file records milestone-level changes. The README describes the converter's
current capabilities without release-by-release notes.

## Unreleased

## 0.36.4 - 2026-07-22

- Reconstruct grouped OfficeArt line connectors (flowchart arrows) from child
  anchors onto the parent Spa position, including line end arrowheads in VML.
- Emit multiple floating shapes that share one document shape character, so
  ungrouped diagram lines are not dropped when textboxes already claim that CP.

## 0.36.3 - 2026-07-22

- Pad short CFB files that omit the final sector's zero padding so FAT chains
  that address the incomplete trailing sector remain readable.
- Treat stale directory sibling/child IDs past the directory entry count as
  absent links instead of aborting.
- Accept JPEG BLIPs that have valid SOI/EOI markers even when OfficeArt record
  length includes non-zero trailing padding after EOI.
- Accept legacy `TableBrc80Operand` diagonal border side bits (`0x10`/`0x20`).
- Keep the first grouped OfficeArt child-anchor geometry when nested walks
  rediscover the same shape id, and keep the first shape when a drawing
  repeats a shape id.
- Ignore trailing bytes after OfficeArt complex property data.
- Deduplicate legacy bookmark names and skip empty/malformed annotation
  comment ranges instead of aborting conversion.
- Sanitize font names that contain non-XML control characters, preferring a
  usable alternate name when the primary name is only controls.
- Skip Word `~$*.doc` lock files in `doc2docx batch`.

## 0.36.2 - 2026-07-22

- Accept complete legacy CFB DIFAT chains that use `FREESECT` as their final
  link, while continuing to reject truncated or count-mismatched chains.
- Validate reusable Word textbox records and their break descriptors without
  treating those non-content placeholders as dangling textboxes.
- Recover inline pictures and embedded OLE previews from main and header
  textbox stories. This restores legacy `EMBED` screenshots that were omitted
  when ObjectPool anchors were scanned only in the main story.
- Preserve cached multi-paragraph `TOC`, `INDEX`, and `TOA` results instead of
  collapsing their paragraph layout, including nested navigation fields and
  cached page numbers.
- Render pictures inside legacy `SHAPE` fields with inline layout semantics,
  synthesize the implicit empty first-page header/footer used by binary Word,
  and prefer explicit twip indents when duplicate character indents would make
  renderers position content inconsistently.
- Validate with 261 passing standard-library regression tests and two real
  Word 97-2003 documents whose 17- and 56-page renderings retain their original
  pagination; the former restores its cover line, logo position, and complete
  table of contents, while the latter preserves all 11 textbox-hosted OLE
  previews.

## 0.36.1 - 2026-07-22

- Accept bookmark PLC terminal CPs bounded by the Piece Table rather than only
  the summed FIB stories, and accept zero-aligned JPEG BLIP padding without
  weakening image validation.
- Reconstruct grouped OfficeArt child-textbox geometry relative to its anchored
  parent, preserve multiple textboxes at one drawing anchor, and defer only
  confirmed children whose group geometry is unavailable.
- Normalize floating WPS Writer tables to their authoritative absolute grid,
  fixed layout, stable indent, and explicit position. Parse redundant legacy
  shading and percentage-width records and safely ignore the exact WPS private
  compatibility markers found alongside complete table and section properties.
- Omit inherited horizontal cell direction and paragraph-frame properties that
  belong to floating table positioning, preventing Word/WPS from rotating or
  flipping individual cell text.
- Validate with 252 passing standard-library regression tests and two real DOC
  files covering the bookmark/JPEG/grouped-diagram and floating-table cases.

## 0.36.0 - 2026-07-22 (M20a-M20g)

### M20a

- Preserve DopBase mirrored-margin and top-gutter flags as native
  `w:mirrorMargins` and `w:gutterAtTop` document settings, so facing-page
  margins and non-side gutter placement remain active after conversion.
- Validate with 188 focused tests and a real Word 97 DOC whose mirrored margins
  and 720-twip top gutter survive structurally and render equivalently. The
  38-file regression batch remains at 36 in-scope successes with no unsupported
  warnings.

### M20b

- Preserve DopBase automatic tab spacing and document hyphenation controls,
  including automatic hyphenation, capital-word behavior, hyphenation zone,
  and the maximum number of consecutive hyphenated lines.
- Emit the corresponding native WordprocessingML settings in schema order and
  reject tab intervals that cannot be represented by `w:defaultTabStop`.
- Validate with 191 focused tests and a real Word 97 DOC that retains the
  360-twip tab interval and automatic-hyphenation switch. LibreOffice
  normalizes the hyphenation zone, consecutive-line limit, and capital-word
  behavior on both DOCX- and RTF-to-DOC export, so those values are
  structurally validated without overstating real-file coverage. The 38-file
  regression batch remains at 36 in-scope successes with no unsupported
  warnings.

### M20c

- Preserve revision tracking and all four document editing-restriction modes
  (`trackedChanges`, `comments`, `forms`, and `readOnly`) from DopBase and the
  authoritative Dop2003 protection fields as native WordprocessingML settings.
- Repair locked revision mode when its required tracking bit is absent, report
  conflicting legacy modes, and reject invalid Dop2003 mode values.
- Deliberately omit incompatible legacy 32-bit password verifiers with an
  explicit diagnostic instead of emitting a modern OOXML hash that could not
  be used to remove protection.

### M20d

- Open XOR-obfuscated, classic RC4, and RC4 CryptoAPI encrypted Word documents
  after password verification, while keeping passwords out of reports and
  recommending password files in the CLI.
- Preserve confirmed ObjectPool storages as native embedded OLE parts with
  exact field anchors, ProgIDs, deterministic relationships, and a standalone
  CFB writer that supports MiniFAT and multi-sector DIFAT chains.

### M20e

- Preserve common floating OfficeArt preset shapes, picture/textbox rotation
  and flips, line dash/cap/join styles, and tight/through wrap polygons; retain
  Macintosh PICT media without pretending every DOCX consumer can render it.
- Preserve custom footnote/endnote reference marks, bookmarks in supported
  secondary stories, safe index-entry fields, and table conditional-style
  properties.

### M20f

- Preserve low-frequency run properties including fit text, underline color,
  character shading/borders, and East Asian vertical/combined layout.
- Apply direct table insert/delete, merge/split, text direction, vertical
  merge/alignment, fit/no-wrap/hide-mark, cell spacing, modern and legacy cell
  shading/borders (including diagonals), RTL layout, and overlap controls while
  keeping dependent cell ranges synchronized.
- Correct implicit-length `sprmPChgTabs` parsing and MiniFAT free-sector
  padding, then validate the cumulative implementation with 236 standard-library
  regression tests.

### M20g

- Preserve complete paragraph-frame positioning, sizing, text distances,
  anchor locking, and text flow, plus floating-table anchors, absolute or
  aligned positions, wrap distances, whole-table shading, and segmented cell
  shading through cells 23–63.
- Expand compact Piece `Prm0` handling to every directly representable
  paragraph and character property, including special object/field anchors,
  frame and East Asian controls, outline/style level changes, character
  animation, Web hiding, and style separators.
- Preserve legacy character shading and borders, explicit complex-script and
  right-to-left run flags, character-unit paragraph indents, nested-indent
  precedence, conditional table-style diagonal borders, and clear-direction
  line breaks. Preserve the structural character state required across
  `sprmCPlain` and character-style resets, and add exact VML paths for arrow,
  thick-arrow, home-plate, line, and plaque OfficeArt presets. Reconstruct
  otherwise unsupported geometry from an available exact wrap contour with a
  dedicated approximation diagnostic, and correct run-property XML schema
  ordering for fit text and East Asian layout.
- Harden CLI limits, password-file decoding, atomic JSON report writes, and
  report collision checks; read one batch password file once, and verify the
  built wheel in an extracted installation state. Validate the cumulative
  implementation with 246 passing standard-library regression tests.

## 0.35.0 - 2026-07-22 (M19a-M19c)

### M19a

- Preserve section chapter-based page numbering, including heading levels 1–9
  and all five MS-DOC separator characters, as native `w:pgNumType`
  `chapStyle`/`chapSep` attributes alongside page format and restart settings.
- Ignore stored separators when chapter numbering is disabled and reject
  heading levels outside the MS-DOC range.
- Validate with 182 focused tests and the unchanged 38-file regression batch:
  all 36 in-scope files convert without unsupported warnings. LibreOffice
  drops these attributes when exporting DOCX to DOC, so no unsupported real
  round-trip claim is made for this property.

### M19b

- Preserve legacy `Brc80` and modern `BrcOperand` top/left/bottom/right page
  borders, including style, width, color, spacing, shadow, and frame settings.
- Parse `sprmSPgbProp` page selection, offset origin, and front/back depth and
  emit the complete native `w:pgBorders` structure in section schema order.
- Validate with 184 focused tests and a real Word 97 DOC whose four red
  16-eighth-point borders, 24-point page offsets, and all-pages/front settings
  survive exactly and render identically. The 38-file regression batch remains
  at 36 in-scope successes with no unsupported warnings.

### M19c

- Preserve first-page and subsequent-page printer paper source identifiers as
  native `w:paperSrc` attributes, including the full unsigned 16-bit range.
- Map the inverse `sprmSFProtected` meaning to explicit section `w:formProt`
  values and preserve right-to-left gutter placement as `w:rtlGutter`, while
  retaining explicit false values and deferring invalid Bool8 operands.
- Validate with 186 focused tests and a real Word 97 DOC whose 720-twip
  right-side gutter survives and renders equivalently. LibreOffice discards
  paper-source and section-protection data on both DOCX- and RTF-to-DOC export,
  so those properties are structurally validated without a false real-file
  round-trip claim. The 38-file regression batch remains unchanged with all 36
  in-scope files converting and no unsupported-property warnings.

## 0.34.0 - 2026-07-22 (M18a-M18c)

### M18a

- Parse bounded `NilPICFAndBinData` records attached to `REF`, `PAGEREF`,
  `NOTEREF`, and `HYPERLINK` fields, validate their HFD headers, and consume the
  redundant U+0001 data marker without emitting a visible placeholder.
- Keep malformed HFD and unsupported form/add-in binary payloads explicitly
  deferred instead of treating arbitrary field data as a raster picture.
- Validate with 176 focused tests and two real DOCs containing five HFD records:
  all five are consumed, the duplicate binary/control warnings are eliminated,
  rendered REF and hyperlink results remain intact, and all 36 in-scope files
  in the 38-file regression batch continue to convert.

### M18b

- Preserve section column separators and top/center/justified/bottom vertical
  alignment as native `w:cols w:sep` and `w:vAlign` properties.
- Repair duplicate `PlcfSed` CPs only when their adjacent Sed metadata and
  parsed Sepx property lists are identical; continue rejecting duplicates that
  could change section semantics.
- Validate with 178 focused tests and a real LibreOffice-authored Word 97 DOC:
  its equivalent empty section is collapsed with a targeted warning, the
  two-column separator renders, and vertical alignment survives structurally.
  The 38-file regression batch remains unchanged with all 36 in-scope files
  converting and no unsupported-property warnings.

### M18c

- Parse indexed `sprmSDxaColWidth` and `sprmSDxaColSpacing` operands for
  complete non-even section layouts and emit native ordered `w:col` children.
- Enforce MS-DOC column index, width, and spacing bounds; retain an explicit
  deferred diagnostic for incomplete width sets, and ignore the equal-column
  default spacing operand when the section uses explicit unequal columns.
- Validate with 180 focused tests and a real Word 97 DOC whose normalized
  2765/5040-twip columns and 500-twip gap survive conversion and render with the
  separator at the narrower first-column boundary. The 38-file regression
  batch remains at 36 in-scope successes with no unsupported warnings.

## 0.33.0 - 2026-07-22 (M17a-M17c)

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
