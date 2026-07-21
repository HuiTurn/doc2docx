# Changelog

This file records milestone-level changes. The README describes the converter's
current capabilities without release-by-release notes.

## Unreleased

- Continue expanding MS-DOC compatibility with specification-backed parsers,
  focused tests, and real Word 97 sample rendering.

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
