"""Minimal deterministic OPC/WordprocessingML package writer."""

from __future__ import annotations

from dataclasses import dataclass, replace
from pathlib import Path
import struct
import zipfile
from xml.etree import ElementTree as ET

from ..errors import PackageWriteError
from ..model import (
    BookmarkEnd,
    BookmarkStart,
    BorderProperties,
    Break,
    BreakType,
    CharacterProperties,
    CommentRangeEnd,
    CommentRangeStart,
    CoreProperties,
    CommentReference,
    ContinuationSeparatorMark,
    Document,
    EmbeddedObject,
    Endnote,
    EndnoteReference,
    Field,
    FloatingPicture,
    FloatingShape,
    FloatingTextBox,
    Footnote,
    FootnoteReference,
    FontDefinition,
    HeaderFooterStory,
    InlinePicture,
    NumberingDefinitions,
    NumberingLevel,
    NoBreakHyphen,
    NoteSeparatorStory,
    Paragraph,
    ParagraphProperties,
    SectionProperties,
    SeparatorMark,
    ShadingProperties,
    ShapeStyle,
    SoftHyphen,
    StyleSheet,
    Symbol,
    Tab,
    Table,
    TableBorders,
    TableCell,
    TableCellMargins,
    TextRun,
)


W_NS = "http://schemas.openxmlformats.org/wordprocessingml/2006/main"
R_NS = "http://schemas.openxmlformats.org/officeDocument/2006/relationships"
REL_NS = "http://schemas.openxmlformats.org/package/2006/relationships"
CONTENT_TYPES_NS = "http://schemas.openxmlformats.org/package/2006/content-types"
OFFICE_DOCUMENT_REL = (
    "http://schemas.openxmlformats.org/officeDocument/2006/relationships/officeDocument"
)
WORD_DOCUMENT_CONTENT_TYPE = (
    "application/vnd.openxmlformats-officedocument.wordprocessingml.document.main+xml"
)
STYLES_CONTENT_TYPE = (
    "application/vnd.openxmlformats-officedocument.wordprocessingml.styles+xml"
)
FONT_TABLE_CONTENT_TYPE = (
    "application/vnd.openxmlformats-officedocument.wordprocessingml.fontTable+xml"
)
HEADER_CONTENT_TYPE = (
    "application/vnd.openxmlformats-officedocument.wordprocessingml.header+xml"
)
FOOTER_CONTENT_TYPE = (
    "application/vnd.openxmlformats-officedocument.wordprocessingml.footer+xml"
)
SETTINGS_CONTENT_TYPE = (
    "application/vnd.openxmlformats-officedocument.wordprocessingml.settings+xml"
)
FOOTNOTES_CONTENT_TYPE = (
    "application/vnd.openxmlformats-officedocument.wordprocessingml.footnotes+xml"
)
ENDNOTES_CONTENT_TYPE = (
    "application/vnd.openxmlformats-officedocument.wordprocessingml.endnotes+xml"
)
COMMENTS_CONTENT_TYPE = (
    "application/vnd.openxmlformats-officedocument.wordprocessingml.comments+xml"
)
NUMBERING_CONTENT_TYPE = (
    "application/vnd.openxmlformats-officedocument.wordprocessingml.numbering+xml"
)
CORE_PROPERTIES_CONTENT_TYPE = (
    "application/vnd.openxmlformats-package.core-properties+xml"
)
STYLES_REL = (
    "http://schemas.openxmlformats.org/officeDocument/2006/relationships/styles"
)
FONT_TABLE_REL = (
    "http://schemas.openxmlformats.org/officeDocument/2006/relationships/fontTable"
)
HEADER_REL = (
    "http://schemas.openxmlformats.org/officeDocument/2006/relationships/header"
)
FOOTER_REL = (
    "http://schemas.openxmlformats.org/officeDocument/2006/relationships/footer"
)
SETTINGS_REL = (
    "http://schemas.openxmlformats.org/officeDocument/2006/relationships/settings"
)
FOOTNOTES_REL = (
    "http://schemas.openxmlformats.org/officeDocument/2006/relationships/footnotes"
)
ENDNOTES_REL = (
    "http://schemas.openxmlformats.org/officeDocument/2006/relationships/endnotes"
)
COMMENTS_REL = (
    "http://schemas.openxmlformats.org/officeDocument/2006/relationships/comments"
)
NUMBERING_REL = (
    "http://schemas.openxmlformats.org/officeDocument/2006/relationships/numbering"
)
CORE_PROPERTIES_REL = (
    "http://schemas.openxmlformats.org/package/2006/relationships/metadata/core-properties"
)
IMAGE_REL = (
    "http://schemas.openxmlformats.org/officeDocument/2006/relationships/image"
)
OLE_OBJECT_REL = (
    "http://schemas.openxmlformats.org/officeDocument/2006/relationships/oleObject"
)
OLE_OBJECT_CONTENT_TYPE = (
    "application/vnd.openxmlformats-officedocument.oleObject"
)
XML_NS = "http://www.w3.org/XML/1998/namespace"
VML_NS = "urn:schemas-microsoft-com:vml"
OFFICE_NS = "urn:schemas-microsoft-com:office:office"
WORD_2003_NS = "urn:schemas-microsoft-com:office:word"
A_NS = "http://schemas.openxmlformats.org/drawingml/2006/main"
WP_NS = "http://schemas.openxmlformats.org/drawingml/2006/wordprocessingDrawing"
PIC_NS = "http://schemas.openxmlformats.org/drawingml/2006/picture"
CP_NS = "http://schemas.openxmlformats.org/package/2006/metadata/core-properties"
DC_NS = "http://purl.org/dc/elements/1.1/"
DCTERMS_NS = "http://purl.org/dc/terms/"
XSI_NS = "http://www.w3.org/2001/XMLSchema-instance"

_VML_PRESET_SHAPES: dict[int, tuple[str, str | None]] = {
    1: ("rect", None),
    2: ("roundrect", None),
    3: ("oval", None),
    4: ("shape", "m10800,0l21600,10800,10800,21600,0,10800xe"),
    5: ("shape", "m10800,0l21600,21600,0,21600xe"),
    6: ("shape", "m0,0l21600,21600,0,21600xe"),
    7: ("shape", "m5400,0l21600,0,16200,21600,0,21600xe"),
    8: ("shape", "m5400,0l16200,0,21600,21600,0,21600xe"),
    9: (
        "shape",
        "m5400,0l16200,0,21600,10800,16200,21600,5400,21600,0,10800xe",
    ),
    10: (
        "shape",
        "m6300,0l15300,0,21600,6300,21600,15300,15300,21600,"
        "6300,21600,0,15300,0,6300xe",
    ),
    11: (
        "shape",
        "m8100,0l13500,0,13500,8100,21600,8100,21600,13500,"
        "13500,13500,13500,21600,8100,21600,8100,13500,0,13500,"
        "0,8100,8100,8100xe",
    ),
    12: (
        "shape",
        "m10800,0l13300,7500,21600,7500,14900,12300,17400,21600,"
        "10800,15800,4200,21600,6700,12300,0,7500,8300,7500xe",
    ),
    13: (
        "shape",
        "m0,8100l12960,8100,12960,0,21600,10800,12960,21600,"
        "12960,13500,0,13500xe",
    ),
    14: (
        "shape",
        "m0,5400l10800,5400,10800,0,21600,10800,10800,21600,"
        "10800,16200,0,16200xe",
    ),
    15: (
        "shape",
        "m0,0l16200,0,21600,10800,16200,21600,0,21600xe",
    ),
    20: ("shape", "m0,0l21600,21600e"),
    21: (
        "shape",
        "m3600,0l18000,0c18000,1980,19620,3600,21600,3600l21600,18000"
        "c19620,18000,18000,19620,18000,21600l3600,21600"
        "c3600,19620,1980,18000,0,18000l0,3600"
        "c1980,3600,3600,1980,3600,0xe",
    ),
}

ET.register_namespace("w", W_NS)
ET.register_namespace("r", R_NS)
ET.register_namespace("v", VML_NS)
ET.register_namespace("o", OFFICE_NS)
ET.register_namespace("w10", WORD_2003_NS)
ET.register_namespace("a", A_NS)
ET.register_namespace("wp", WP_NS)
ET.register_namespace("pic", PIC_NS)
ET.register_namespace("cp", CP_NS)
ET.register_namespace("dc", DC_NS)
ET.register_namespace("dcterms", DCTERMS_NS)
ET.register_namespace("xsi", XSI_NS)


@dataclass(slots=True, frozen=True)
class _HeaderFooterPart:
    section_key: tuple[int, int]
    kind: str
    reference_type: str
    part_name: str
    relationship_id: str
    story: HeaderFooterStory


def _pictures_in_inlines(
    inlines: tuple[object, ...],
) -> tuple[InlinePicture | FloatingPicture, ...]:
    pictures: list[InlinePicture | FloatingPicture] = []
    for inline in inlines:
        if isinstance(inline, (InlinePicture, FloatingPicture)):
            pictures.append(inline)
        elif isinstance(inline, EmbeddedObject) and inline.preview is not None:
            pictures.append(inline.preview)
        elif isinstance(inline, Field):
            pictures.extend(_pictures_in_inlines(inline.result))
        elif isinstance(inline, FloatingTextBox):
            pictures.extend(_pictures_in_blocks(inline.body_blocks))
    return tuple(pictures)


def _pictures_in_blocks(
    blocks: tuple[Paragraph | Table, ...],
) -> tuple[InlinePicture | FloatingPicture, ...]:
    pictures: list[InlinePicture | FloatingPicture] = []
    for block in blocks:
        if isinstance(block, Paragraph):
            pictures.extend(_pictures_in_inlines(block.inlines))
            continue
        for row in block.rows:
            for cell in row.cells:
                pictures.extend(_pictures_in_blocks(cell.body_blocks))
    # One relationship per target is sufficient even when a drawing is reused.
    return tuple({picture.picture_id: picture for picture in pictures}.values())


def _pictures_in_note_part(
    values: tuple[Footnote, ...] | tuple[Endnote, ...],
    separator_stories: tuple[NoteSeparatorStory | None, ...],
) -> tuple[InlinePicture | FloatingPicture, ...]:
    pictures: dict[int, InlinePicture | FloatingPicture] = {}
    for value in values:
        for picture in _pictures_in_blocks(value.body_blocks):
            pictures[picture.picture_id] = picture
    for story in separator_stories:
        if story is None:
            continue
        for picture in _pictures_in_blocks(story.body_blocks):
            pictures[picture.picture_id] = picture
    return tuple(pictures.values())


def _qn(namespace: str, local_name: str) -> str:
    return f"{{{namespace}}}{local_name}"


def _xml_bytes(root: ET.Element) -> bytes:
    return ET.tostring(root, encoding="utf-8", xml_declaration=True)


def _content_types_xml(
    *,
    has_styles: bool,
    has_fonts: bool,
    has_settings: bool,
    has_footnotes: bool,
    has_endnotes: bool,
    has_comments: bool,
    has_numbering: bool,
    has_core_properties: bool,
    pictures: tuple[InlinePicture | FloatingPicture, ...],
    embedded_objects: tuple[EmbeddedObject, ...],
    header_footer_parts: tuple[_HeaderFooterPart, ...],
) -> bytes:
    # OPC consumers in the wild are more interoperable with the conventional
    # default namespace form than with an equivalent generated prefix.
    root = ET.Element("Types", xmlns=CONTENT_TYPES_NS)
    ET.SubElement(
        root,
        "Default",
        Extension="rels",
        ContentType="application/vnd.openxmlformats-package.relationships+xml",
    )
    ET.SubElement(
        root,
        "Default",
        Extension="xml",
        ContentType="application/xml",
    )
    if embedded_objects:
        ET.SubElement(
            root,
            "Default",
            Extension="bin",
            ContentType=OLE_OBJECT_CONTENT_TYPE,
        )
    image_content_types: dict[str, str] = {}
    for picture in pictures:
        previous = image_content_types.setdefault(
            picture.extension,
            picture.content_type,
        )
        if previous != picture.content_type:
            raise PackageWriteError(
                f"image extension {picture.extension!r} has conflicting content types"
            )
    for extension, content_type in sorted(image_content_types.items()):
        ET.SubElement(
            root,
            "Default",
            Extension=extension,
            ContentType=content_type,
        )
    ET.SubElement(
        root,
        "Override",
        PartName="/word/document.xml",
        ContentType=WORD_DOCUMENT_CONTENT_TYPE,
    )
    if has_core_properties:
        ET.SubElement(
            root,
            "Override",
            PartName="/docProps/core.xml",
            ContentType=CORE_PROPERTIES_CONTENT_TYPE,
        )
    if has_styles:
        ET.SubElement(
            root,
            "Override",
            PartName="/word/styles.xml",
            ContentType=STYLES_CONTENT_TYPE,
        )
    if has_fonts:
        ET.SubElement(
            root,
            "Override",
            PartName="/word/fontTable.xml",
            ContentType=FONT_TABLE_CONTENT_TYPE,
        )
    if has_settings:
        ET.SubElement(
            root,
            "Override",
            PartName="/word/settings.xml",
            ContentType=SETTINGS_CONTENT_TYPE,
        )
    if has_footnotes:
        ET.SubElement(
            root,
            "Override",
            PartName="/word/footnotes.xml",
            ContentType=FOOTNOTES_CONTENT_TYPE,
        )
    if has_endnotes:
        ET.SubElement(
            root,
            "Override",
            PartName="/word/endnotes.xml",
            ContentType=ENDNOTES_CONTENT_TYPE,
        )
    if has_comments:
        ET.SubElement(
            root,
            "Override",
            PartName="/word/comments.xml",
            ContentType=COMMENTS_CONTENT_TYPE,
        )
    if has_numbering:
        ET.SubElement(
            root,
            "Override",
            PartName="/word/numbering.xml",
            ContentType=NUMBERING_CONTENT_TYPE,
        )
    for part in header_footer_parts:
        ET.SubElement(
            root,
            "Override",
            PartName=f"/word/{part.part_name}",
            ContentType=(
                HEADER_CONTENT_TYPE if part.kind == "header" else FOOTER_CONTENT_TYPE
            ),
        )
    return _xml_bytes(root)


def _root_relationships_xml(*, has_core_properties: bool) -> bytes:
    root = ET.Element("Relationships", xmlns=REL_NS)
    ET.SubElement(
        root,
        "Relationship",
        Id="rId1",
        Type=OFFICE_DOCUMENT_REL,
        Target="word/document.xml",
    )
    if has_core_properties:
        ET.SubElement(
            root,
            "Relationship",
            Id="rId2",
            Type=CORE_PROPERTIES_REL,
            Target="docProps/core.xml",
        )
    return _xml_bytes(root)


def _document_relationships_xml(
    *,
    has_styles: bool,
    has_fonts: bool,
    has_settings: bool,
    has_footnotes: bool,
    has_endnotes: bool,
    has_comments: bool,
    has_numbering: bool,
    pictures: tuple[InlinePicture | FloatingPicture, ...],
    embedded_objects: tuple[EmbeddedObject, ...],
    header_footer_parts: tuple[_HeaderFooterPart, ...],
) -> bytes:
    root = ET.Element("Relationships", xmlns=REL_NS)
    relationship_id = 1
    if has_styles:
        ET.SubElement(
            root,
            "Relationship",
            Id=f"rId{relationship_id}",
            Type=STYLES_REL,
            Target="styles.xml",
        )
        relationship_id += 1
    if has_fonts:
        ET.SubElement(
            root,
            "Relationship",
            Id=f"rId{relationship_id}",
            Type=FONT_TABLE_REL,
            Target="fontTable.xml",
        )
        relationship_id += 1
    if has_settings:
        ET.SubElement(
            root,
            "Relationship",
            Id=f"rId{relationship_id}",
            Type=SETTINGS_REL,
            Target="settings.xml",
        )
        relationship_id += 1
    if has_footnotes:
        ET.SubElement(
            root,
            "Relationship",
            Id=f"rId{relationship_id}",
            Type=FOOTNOTES_REL,
            Target="footnotes.xml",
        )
        relationship_id += 1
    if has_endnotes:
        ET.SubElement(
            root,
            "Relationship",
            Id=f"rId{relationship_id}",
            Type=ENDNOTES_REL,
            Target="endnotes.xml",
        )
        relationship_id += 1
    if has_comments:
        ET.SubElement(
            root,
            "Relationship",
            Id=f"rId{relationship_id}",
            Type=COMMENTS_REL,
            Target="comments.xml",
        )
        relationship_id += 1
    if has_numbering:
        ET.SubElement(
            root,
            "Relationship",
            Id=f"rId{relationship_id}",
            Type=NUMBERING_REL,
            Target="numbering.xml",
        )
        relationship_id += 1
    for picture in pictures:
        ET.SubElement(
            root,
            "Relationship",
            Id=f"rIdImage{picture.picture_id}",
            Type=IMAGE_REL,
            Target=f"media/image{picture.picture_id}.{picture.extension}",
        )
    for embedded_object in embedded_objects:
        ET.SubElement(
            root,
            "Relationship",
            Id=f"rIdOleObject{embedded_object.object_id}",
            Type=OLE_OBJECT_REL,
            Target=(
                f"embeddings/oleObject{embedded_object.object_id}.bin"
            ),
        )
    for part in header_footer_parts:
        ET.SubElement(
            root,
            "Relationship",
            Id=part.relationship_id,
            Type=HEADER_REL if part.kind == "header" else FOOTER_REL,
            Target=part.part_name,
        )
    return _xml_bytes(root)


def _image_relationships_xml(
    pictures: tuple[InlinePicture | FloatingPicture, ...],
) -> bytes:
    root = ET.Element("Relationships", xmlns=REL_NS)
    for picture in pictures:
        ET.SubElement(
            root,
            "Relationship",
            Id=f"rIdImage{picture.picture_id}",
            Type=IMAGE_REL,
            Target=f"media/image{picture.picture_id}.{picture.extension}",
        )
    return _xml_bytes(root)


def _build_header_footer_parts(
    document: Document,
    *,
    has_styles: bool,
    has_fonts: bool,
    has_settings: bool,
    has_footnotes: bool,
    has_endnotes: bool,
    has_comments: bool,
    has_numbering: bool,
) -> tuple[_HeaderFooterPart, ...]:
    relationship_number = 1 + sum(
        (
            has_styles,
            has_fonts,
            has_settings,
            has_footnotes,
            has_endnotes,
            has_comments,
            has_numbering,
        )
    )
    header_number = 0
    footer_number = 0
    parts: list[_HeaderFooterPart] = []
    slots = (
        ("default_header", "header", "default"),
        ("even_header", "header", "even"),
        ("first_header", "header", "first"),
        ("default_footer", "footer", "default"),
        ("even_footer", "footer", "even"),
        ("first_footer", "footer", "first"),
    )
    for section in document.sections:
        for field_name, kind, reference_type in slots:
            story = getattr(section, field_name)
            if story is None:
                continue
            if kind == "header":
                header_number += 1
                part_name = f"header{header_number}.xml"
            else:
                footer_number += 1
                part_name = f"footer{footer_number}.xml"
            parts.append(
                _HeaderFooterPart(
                    section_key=(section.cp_start, section.cp_end),
                    kind=kind,
                    reference_type=reference_type,
                    part_name=part_name,
                    relationship_id=f"rId{relationship_number}",
                    story=story,
                )
            )
            relationship_number += 1
    return tuple(parts)


def _append_boolean_property(
    parent: ET.Element,
    name: str,
    value: bool | None,
) -> None:
    if value is None:
        return
    element = ET.SubElement(parent, _qn(W_NS, name))
    if not value:
        element.set(_qn(W_NS, "val"), "0")


def _has_character_properties(properties: CharacterProperties) -> bool:
    return replace(
        properties,
        picture_location=None,
        picture_is_binary=None,
        ole_object=None,
        object_placeholder=None,
        line_break_clear=None,
        revision_format_id=None,
        revision_text_id=None,
    ) != CharacterProperties()


def _append_character_property_elements(
    run_properties: ET.Element,
    properties: CharacterProperties,
    *,
    valid_style_ids: set[int] | None = None,
) -> None:
    if (
        properties.style_id is not None
        and (valid_style_ids is None or properties.style_id in valid_style_ids)
    ):
        ET.SubElement(
            run_properties,
            _qn(W_NS, "rStyle"),
            {_qn(W_NS, "val"): f"DocStyle{properties.style_id}"},
        )
    font_attributes: dict[str, str] = {}
    if properties.ascii_font is not None:
        font_attributes[_qn(W_NS, "ascii")] = properties.ascii_font
    if properties.high_ansi_font is not None:
        font_attributes[_qn(W_NS, "hAnsi")] = properties.high_ansi_font
    if properties.east_asia_font is not None:
        font_attributes[_qn(W_NS, "eastAsia")] = properties.east_asia_font
    if properties.complex_script_font is not None:
        font_attributes[_qn(W_NS, "cs")] = properties.complex_script_font
    if properties.font_hint is not None:
        font_attributes[_qn(W_NS, "hint")] = properties.font_hint
    if font_attributes:
        ET.SubElement(run_properties, _qn(W_NS, "rFonts"), font_attributes)
    _append_boolean_property(run_properties, "b", properties.bold)
    _append_boolean_property(
        run_properties,
        "bCs",
        properties.complex_script_bold,
    )
    _append_boolean_property(run_properties, "i", properties.italic)
    _append_boolean_property(
        run_properties,
        "iCs",
        properties.complex_script_italic,
    )
    _append_boolean_property(run_properties, "caps", properties.caps)
    _append_boolean_property(run_properties, "smallCaps", properties.small_caps)
    _append_boolean_property(run_properties, "strike", properties.strike)
    _append_boolean_property(run_properties, "dstrike", properties.double_strike)
    _append_boolean_property(run_properties, "outline", properties.outline)
    _append_boolean_property(run_properties, "shadow", properties.shadow)
    _append_boolean_property(run_properties, "emboss", properties.emboss)
    _append_boolean_property(run_properties, "imprint", properties.imprint)
    _append_boolean_property(run_properties, "noProof", properties.no_proof)
    _append_boolean_property(run_properties, "snapToGrid", properties.snap_to_grid)
    _append_boolean_property(run_properties, "vanish", properties.hidden)
    _append_boolean_property(run_properties, "webHidden", properties.web_hidden)
    if properties.color is not None:
        ET.SubElement(
            run_properties,
            _qn(W_NS, "color"),
            {_qn(W_NS, "val"): properties.color},
        )
    if properties.spacing_twips is not None:
        ET.SubElement(
            run_properties,
            _qn(W_NS, "spacing"),
            {_qn(W_NS, "val"): str(properties.spacing_twips)},
        )
    if properties.scale_percent is not None:
        ET.SubElement(
            run_properties,
            _qn(W_NS, "w"),
            {_qn(W_NS, "val"): str(properties.scale_percent)},
        )
    if properties.kerning_half_points is not None:
        ET.SubElement(
            run_properties,
            _qn(W_NS, "kern"),
            {_qn(W_NS, "val"): str(properties.kerning_half_points)},
        )
    if properties.position_half_points is not None:
        ET.SubElement(
            run_properties,
            _qn(W_NS, "position"),
            {_qn(W_NS, "val"): str(properties.position_half_points)},
        )
    if properties.size_half_points is not None:
        attributes = {_qn(W_NS, "val"): str(properties.size_half_points)}
        ET.SubElement(run_properties, _qn(W_NS, "sz"), attributes)
    if properties.complex_script_size_half_points is not None:
        ET.SubElement(
            run_properties,
            _qn(W_NS, "szCs"),
            {
                _qn(W_NS, "val"): str(
                    properties.complex_script_size_half_points
                )
            },
        )
    if properties.highlight is not None:
        ET.SubElement(
            run_properties,
            _qn(W_NS, "highlight"),
            {_qn(W_NS, "val"): properties.highlight},
        )
    if properties.underline is not None:
        underline_attributes = {_qn(W_NS, "val"): properties.underline}
        if properties.underline_color is not None:
            underline_attributes[_qn(W_NS, "color")] = (
                properties.underline_color
            )
        ET.SubElement(
            run_properties,
            _qn(W_NS, "u"),
            underline_attributes,
        )
    if properties.text_effect is not None:
        ET.SubElement(
            run_properties,
            _qn(W_NS, "effect"),
            {_qn(W_NS, "val"): properties.text_effect},
        )
    if properties.border is not None:
        ET.SubElement(
            run_properties,
            _qn(W_NS, "bdr"),
            _border_attributes(properties.border),
        )
    _append_shading(run_properties, properties.shading)
    if properties.fit_text_width_twips is not None:
        fit_text_attributes = {
            _qn(W_NS, "val"): str(properties.fit_text_width_twips),
        }
        if properties.fit_text_id is not None:
            fit_text_attributes[_qn(W_NS, "id")] = str(properties.fit_text_id)
        ET.SubElement(
            run_properties,
            _qn(W_NS, "fitText"),
            fit_text_attributes,
        )
    if properties.vertical_align is not None:
        ET.SubElement(
            run_properties,
            _qn(W_NS, "vertAlign"),
            {_qn(W_NS, "val"): properties.vertical_align},
        )
    _append_boolean_property(run_properties, "rtl", properties.bidirectional)
    _append_boolean_property(run_properties, "cs", properties.complex_script)
    if properties.emphasis is not None:
        ET.SubElement(
            run_properties,
            _qn(W_NS, "em"),
            {_qn(W_NS, "val"): properties.emphasis},
        )
    language_attributes: dict[str, str] = {}
    if properties.language is not None:
        language_attributes[_qn(W_NS, "val")] = properties.language
    if properties.east_asia_language is not None:
        language_attributes[_qn(W_NS, "eastAsia")] = properties.east_asia_language
    if properties.complex_script_language is not None:
        language_attributes[_qn(W_NS, "bidi")] = properties.complex_script_language
    if language_attributes:
        ET.SubElement(run_properties, _qn(W_NS, "lang"), language_attributes)
    if (
        properties.east_asian_vertical is not None
        or properties.east_asian_combine is not None
        or properties.east_asian_combine_brackets is not None
        or properties.east_asian_vertical_compress is not None
        or properties.east_asian_layout_id is not None
    ):
        east_asian_attributes: dict[str, str] = {}
        if properties.east_asian_vertical is not None:
            east_asian_attributes[_qn(W_NS, "vert")] = (
                "1" if properties.east_asian_vertical else "0"
            )
        if properties.east_asian_combine is not None:
            east_asian_attributes[_qn(W_NS, "combine")] = (
                "1" if properties.east_asian_combine else "0"
            )
        if properties.east_asian_combine_brackets is not None:
            east_asian_attributes[_qn(W_NS, "combineBrackets")] = (
                properties.east_asian_combine_brackets
            )
        if properties.east_asian_vertical_compress is not None:
            east_asian_attributes[_qn(W_NS, "vertCompress")] = (
                "1" if properties.east_asian_vertical_compress else "0"
            )
        if properties.east_asian_layout_id is not None:
            east_asian_attributes[_qn(W_NS, "id")] = str(
                properties.east_asian_layout_id
            )
        ET.SubElement(
            run_properties,
            _qn(W_NS, "eastAsianLayout"),
            east_asian_attributes,
        )
    _append_boolean_property(
        run_properties,
        "specVanish",
        properties.special_vanish,
    )


def _append_run_properties(
    run: ET.Element,
    properties: CharacterProperties,
    *,
    valid_style_ids: set[int] | None = None,
) -> None:
    if properties.revision_text_id is not None:
        run.set(_qn(W_NS, "rsidR"), f"{properties.revision_text_id:08X}")
    if properties.revision_format_id is not None:
        run.set(
            _qn(W_NS, "rsidRPr"),
            f"{properties.revision_format_id:08X}",
        )
    if not _has_character_properties(properties):
        return
    run_properties = ET.SubElement(run, _qn(W_NS, "rPr"))
    _append_character_property_elements(
        run_properties,
        properties,
        valid_style_ids=valid_style_ids,
    )


def _append_paragraph_properties(
    paragraph: ET.Element,
    properties: ParagraphProperties,
    *,
    valid_style_ids: set[int] | None = None,
    mark_properties: CharacterProperties | None = None,
    valid_mark_style_ids: set[int] | None = None,
) -> None:
    mark_properties = mark_properties or CharacterProperties()
    serializable = (
        (
            properties.style_id is not None
            and (valid_style_ids is None or properties.style_id in valid_style_ids)
        )
        or properties.justification is not None
        or properties.keep_lines is not None
        or properties.keep_next is not None
        or properties.page_break_before is not None
        or properties.outline_level is not None
        or properties.widow_control is not None
        or properties.suppress_line_numbers is not None
        or properties.suppress_auto_hyphens is not None
        or properties.contextual_spacing is not None
        or properties.auto_spacing_before is not None
        or properties.auto_spacing_after is not None
        or properties.bidirectional is not None
        or properties.kinsoku is not None
        or properties.word_wrap is not None
        or properties.overflow_punctuation is not None
        or properties.top_line_punctuation is not None
        or properties.auto_space_east_asian_latin is not None
        or properties.auto_space_east_asian_numbers is not None
        or properties.snap_to_grid is not None
        or properties.adjust_right_indent is not None
        or properties.text_alignment is not None
        or properties.mirror_indents is not None
        or properties.textbox_tight_wrap is not None
        or (properties.frame is not None and not properties.in_table)
        or properties.borders is not None
        or properties.shading is not None
        or properties.tab_stops is not None
        or properties.left_indent_twips is not None
        or properties.right_indent_twips is not None
        or properties.first_line_indent_twips is not None
        or properties.left_indent_chars is not None
        or properties.right_indent_chars is not None
        or properties.first_line_indent_chars is not None
        or properties.space_before_twips is not None
        or properties.space_after_twips is not None
        or properties.space_before_lines is not None
        or properties.space_after_lines is not None
        or properties.line_spacing_twips is not None
        or properties.numbering_id is not None
        or properties.numbering_level is not None
        or properties.numbering_suppressed is True
        or properties.numbering_skipped is True
        or _has_character_properties(mark_properties)
    )
    if not serializable:
        return
    paragraph_properties = ET.SubElement(paragraph, _qn(W_NS, "pPr"))
    if (
        properties.style_id is not None
        and (valid_style_ids is None or properties.style_id in valid_style_ids)
    ):
        ET.SubElement(
            paragraph_properties,
            _qn(W_NS, "pStyle"),
            {_qn(W_NS, "val"): f"DocStyle{properties.style_id}"},
        )
    _append_boolean_property(
        paragraph_properties,
        "keepNext",
        properties.keep_next,
    )
    _append_boolean_property(
        paragraph_properties,
        "keepLines",
        properties.keep_lines,
    )
    _append_boolean_property(
        paragraph_properties,
        "pageBreakBefore",
        properties.page_break_before,
    )
    if properties.frame is not None and not properties.in_table:
        frame_attributes: dict[str, str] = {}
        if properties.frame.drop_cap is not None:
            frame_attributes[_qn(W_NS, "dropCap")] = properties.frame.drop_cap
        if properties.frame.drop_cap_lines is not None:
            frame_attributes[_qn(W_NS, "lines")] = str(
                properties.frame.drop_cap_lines
            )
        if properties.frame.horizontal_anchor is not None:
            frame_attributes[_qn(W_NS, "hAnchor")] = (
                properties.frame.horizontal_anchor
            )
        if properties.frame.vertical_anchor is not None:
            frame_attributes[_qn(W_NS, "vAnchor")] = (
                properties.frame.vertical_anchor
            )
        if properties.frame.wrap is not None:
            frame_attributes[_qn(W_NS, "wrap")] = properties.frame.wrap
        if properties.frame.horizontal_position_twips is not None:
            frame_attributes[_qn(W_NS, "x")] = str(
                properties.frame.horizontal_position_twips
            )
        if properties.frame.horizontal_alignment is not None:
            frame_attributes[_qn(W_NS, "xAlign")] = (
                properties.frame.horizontal_alignment
            )
        if properties.frame.vertical_position_twips is not None:
            frame_attributes[_qn(W_NS, "y")] = str(
                properties.frame.vertical_position_twips
            )
        if properties.frame.vertical_alignment is not None:
            frame_attributes[_qn(W_NS, "yAlign")] = (
                properties.frame.vertical_alignment
            )
        if properties.frame.width_twips is not None:
            frame_attributes[_qn(W_NS, "w")] = str(
                properties.frame.width_twips
            )
        if properties.frame.height_twips is not None:
            frame_attributes[_qn(W_NS, "h")] = str(
                properties.frame.height_twips
            )
        if properties.frame.height_rule is not None:
            frame_attributes[_qn(W_NS, "hRule")] = properties.frame.height_rule
        if properties.frame.horizontal_space_twips is not None:
            frame_attributes[_qn(W_NS, "hSpace")] = str(
                properties.frame.horizontal_space_twips
            )
        if properties.frame.vertical_space_twips is not None:
            frame_attributes[_qn(W_NS, "vSpace")] = str(
                properties.frame.vertical_space_twips
            )
        if properties.frame.anchor_locked is not None:
            frame_attributes[_qn(W_NS, "anchorLock")] = (
                "1" if properties.frame.anchor_locked else "0"
            )
        if properties.frame.text_direction is not None:
            frame_attributes[_qn(W_NS, "vert")] = (
                properties.frame.text_direction
            )
        ET.SubElement(
            paragraph_properties,
            _qn(W_NS, "framePr"),
            frame_attributes,
        )
    _append_boolean_property(
        paragraph_properties,
        "widowControl",
        properties.widow_control,
    )
    if (
        properties.numbering_id is not None
        or properties.numbering_level is not None
        or properties.numbering_suppressed is True
        or properties.numbering_skipped is True
    ):
        numbering_properties = ET.SubElement(
            paragraph_properties,
            _qn(W_NS, "numPr"),
        )
        numbering_disabled = (
            properties.numbering_suppressed is True
            or properties.numbering_skipped is True
        )
        if not numbering_disabled:
            if properties.numbering_level is not None:
                level = properties.numbering_level
            elif properties.numbering_id is not None:
                level = 0
            else:
                level = None
            if level is not None:
                ET.SubElement(
                    numbering_properties,
                    _qn(W_NS, "ilvl"),
                    {_qn(W_NS, "val"): str(level)},
                )
        if numbering_disabled:
            numbering_id = 0
        else:
            numbering_id = properties.numbering_id
        if numbering_id is not None:
            ET.SubElement(
                numbering_properties,
                _qn(W_NS, "numId"),
                {_qn(W_NS, "val"): str(numbering_id)},
            )
    _append_boolean_property(
        paragraph_properties,
        "suppressLineNumbers",
        properties.suppress_line_numbers,
    )
    if properties.borders is not None:
        _append_borders(
            paragraph_properties,
            "pBdr",
            properties.borders,
            include_inside=False,
        )
    _append_shading(paragraph_properties, properties.shading)
    if properties.tab_stops:
        tabs = ET.SubElement(paragraph_properties, _qn(W_NS, "tabs"))
        for tab_stop in properties.tab_stops:
            attributes = {
                _qn(W_NS, "val"): tab_stop.alignment,
                _qn(W_NS, "pos"): str(tab_stop.position_twips),
            }
            if tab_stop.leader is not None:
                attributes[_qn(W_NS, "leader")] = tab_stop.leader
            ET.SubElement(tabs, _qn(W_NS, "tab"), attributes)
    _append_boolean_property(
        paragraph_properties,
        "suppressAutoHyphens",
        properties.suppress_auto_hyphens,
    )
    _append_boolean_property(paragraph_properties, "kinsoku", properties.kinsoku)
    _append_boolean_property(paragraph_properties, "wordWrap", properties.word_wrap)
    _append_boolean_property(
        paragraph_properties,
        "overflowPunct",
        properties.overflow_punctuation,
    )
    _append_boolean_property(
        paragraph_properties,
        "topLinePunct",
        properties.top_line_punctuation,
    )
    _append_boolean_property(
        paragraph_properties,
        "autoSpaceDE",
        properties.auto_space_east_asian_latin,
    )
    _append_boolean_property(
        paragraph_properties,
        "autoSpaceDN",
        properties.auto_space_east_asian_numbers,
    )
    _append_boolean_property(
        paragraph_properties,
        "bidi",
        properties.bidirectional,
    )
    _append_boolean_property(
        paragraph_properties,
        "adjustRightInd",
        properties.adjust_right_indent,
    )
    _append_boolean_property(
        paragraph_properties,
        "snapToGrid",
        properties.snap_to_grid,
    )
    if properties.text_alignment is not None:
        ET.SubElement(
            paragraph_properties,
            _qn(W_NS, "textAlignment"),
            {_qn(W_NS, "val"): properties.text_alignment},
        )
    _append_boolean_property(
        paragraph_properties,
        "mirrorIndents",
        properties.mirror_indents,
    )
    if properties.textbox_tight_wrap is not None:
        ET.SubElement(
            paragraph_properties,
            _qn(W_NS, "textboxTightWrap"),
            {_qn(W_NS, "val"): properties.textbox_tight_wrap},
        )
    spacing: dict[str, str] = {}
    if properties.space_before_twips is not None:
        spacing[_qn(W_NS, "before")] = str(properties.space_before_twips)
    if properties.space_after_twips is not None:
        spacing[_qn(W_NS, "after")] = str(properties.space_after_twips)
    if properties.space_before_lines is not None:
        spacing[_qn(W_NS, "beforeLines")] = str(properties.space_before_lines)
    if properties.space_after_lines is not None:
        spacing[_qn(W_NS, "afterLines")] = str(properties.space_after_lines)
    if properties.line_spacing_twips is not None:
        spacing[_qn(W_NS, "line")] = str(properties.line_spacing_twips)
    if properties.line_rule is not None:
        spacing[_qn(W_NS, "lineRule")] = properties.line_rule
    if properties.auto_spacing_before is not None:
        spacing[_qn(W_NS, "beforeAutospacing")] = (
            "1" if properties.auto_spacing_before else "0"
        )
    if properties.auto_spacing_after is not None:
        spacing[_qn(W_NS, "afterAutospacing")] = (
            "1" if properties.auto_spacing_after else "0"
        )
    if spacing:
        ET.SubElement(paragraph_properties, _qn(W_NS, "spacing"), spacing)
    indentation: dict[str, str] = {}
    if properties.left_indent_twips is not None:
        indentation[_qn(W_NS, "left")] = str(properties.left_indent_twips)
    if properties.right_indent_twips is not None:
        indentation[_qn(W_NS, "right")] = str(properties.right_indent_twips)
    if properties.first_line_indent_twips is not None:
        if properties.first_line_indent_twips < 0:
            indentation[_qn(W_NS, "hanging")] = str(
                -properties.first_line_indent_twips
            )
        else:
            indentation[_qn(W_NS, "firstLine")] = str(
                properties.first_line_indent_twips
            )
    if (
        properties.left_indent_chars is not None
        and properties.left_indent_twips is None
    ):
        indentation[_qn(W_NS, "leftChars")] = str(properties.left_indent_chars)
    if (
        properties.right_indent_chars is not None
        and properties.right_indent_twips is None
    ):
        indentation[_qn(W_NS, "rightChars")] = str(properties.right_indent_chars)
    if (
        properties.first_line_indent_chars is not None
        and properties.first_line_indent_twips is None
    ):
        if properties.first_line_indent_chars < 0:
            indentation[_qn(W_NS, "hangingChars")] = str(
                -properties.first_line_indent_chars
            )
        else:
            indentation[_qn(W_NS, "firstLineChars")] = str(
                properties.first_line_indent_chars
            )
    if indentation:
        ET.SubElement(paragraph_properties, _qn(W_NS, "ind"), indentation)
    _append_boolean_property(
        paragraph_properties,
        "contextualSpacing",
        properties.contextual_spacing,
    )
    if properties.justification is not None:
        ET.SubElement(
            paragraph_properties,
            _qn(W_NS, "jc"),
            {_qn(W_NS, "val"): properties.justification},
        )
    if properties.outline_level is not None:
        ET.SubElement(
            paragraph_properties,
            _qn(W_NS, "outlineLvl"),
            {_qn(W_NS, "val"): str(properties.outline_level)},
        )
    if _has_character_properties(mark_properties):
        mark_run_properties = ET.SubElement(
            paragraph_properties,
            _qn(W_NS, "rPr"),
        )
        _append_character_property_elements(
            mark_run_properties,
            mark_properties,
            valid_style_ids=valid_mark_style_ids,
        )


def _append_text_run(
    paragraph_element: ET.Element,
    text: str,
    properties: CharacterProperties,
    *,
    valid_style_ids: set[int],
) -> None:
    run = ET.SubElement(paragraph_element, _qn(W_NS, "r"))
    _append_run_properties(run, properties, valid_style_ids=valid_style_ids)
    text_element = ET.SubElement(run, _qn(W_NS, "t"))
    if text[:1].isspace() or text[-1:].isspace() or "  " in text:
        text_element.set(_qn(XML_NS, "space"), "preserve")
    text_element.text = text


def _append_symbol(
    paragraph_element: ET.Element,
    symbol: Symbol,
    *,
    valid_style_ids: set[int],
) -> None:
    run = ET.SubElement(paragraph_element, _qn(W_NS, "r"))
    _append_run_properties(
        run,
        symbol.properties,
        valid_style_ids=valid_style_ids,
    )
    ET.SubElement(
        run,
        _qn(W_NS, "sym"),
        {
            _qn(W_NS, "font"): symbol.font,
            _qn(W_NS, "char"): f"{symbol.character_code:04X}",
        },
    )


def _append_picture_graphic(
    container: ET.Element,
    picture: InlinePicture | FloatingPicture,
    *,
    width_emu: int,
    height_emu: int,
    rotation_degrees: float = 0.0,
    flip_horizontal: bool = False,
    flip_vertical: bool = False,
) -> None:
    picture_name = picture.name or f"Picture {picture.picture_id}"
    ET.SubElement(
        container,
        _qn(WP_NS, "docPr"),
        {"id": str(picture.picture_id), "name": picture_name},
    )
    frame_properties = ET.SubElement(
        container,
        _qn(WP_NS, "cNvGraphicFramePr"),
    )
    ET.SubElement(
        frame_properties,
        _qn(A_NS, "graphicFrameLocks"),
        {"noChangeAspect": "1"},
    )
    graphic = ET.SubElement(container, _qn(A_NS, "graphic"))
    graphic_data = ET.SubElement(
        graphic,
        _qn(A_NS, "graphicData"),
        {"uri": PIC_NS},
    )
    picture_element = ET.SubElement(graphic_data, _qn(PIC_NS, "pic"))
    non_visual = ET.SubElement(picture_element, _qn(PIC_NS, "nvPicPr"))
    ET.SubElement(
        non_visual,
        _qn(PIC_NS, "cNvPr"),
        {"id": str(picture.picture_id), "name": picture_name},
    )
    non_visual_properties = ET.SubElement(non_visual, _qn(PIC_NS, "cNvPicPr"))
    ET.SubElement(
        non_visual_properties,
        _qn(A_NS, "picLocks"),
        {"noChangeAspect": "1"},
    )
    blip_fill = ET.SubElement(picture_element, _qn(PIC_NS, "blipFill"))
    ET.SubElement(
        blip_fill,
        _qn(A_NS, "blip"),
        {_qn(R_NS, "embed"): f"rIdImage{picture.picture_id}"},
    )
    stretch = ET.SubElement(blip_fill, _qn(A_NS, "stretch"))
    ET.SubElement(stretch, _qn(A_NS, "fillRect"))
    shape_properties = ET.SubElement(picture_element, _qn(PIC_NS, "spPr"))
    transform_attributes: dict[str, str] = {}
    if rotation_degrees:
        transform_attributes["rot"] = str(round(rotation_degrees * 60000))
    if flip_horizontal:
        transform_attributes["flipH"] = "1"
    if flip_vertical:
        transform_attributes["flipV"] = "1"
    transform = ET.SubElement(
        shape_properties,
        _qn(A_NS, "xfrm"),
        transform_attributes,
    )
    ET.SubElement(transform, _qn(A_NS, "off"), {"x": "0", "y": "0"})
    ET.SubElement(
        transform,
        _qn(A_NS, "ext"),
        {"cx": str(width_emu), "cy": str(height_emu)},
    )
    geometry = ET.SubElement(
        shape_properties,
        _qn(A_NS, "prstGeom"),
        {"prst": "rect"},
    )
    ET.SubElement(geometry, _qn(A_NS, "avLst"))


def _append_inline_picture(
    paragraph_element: ET.Element,
    picture: InlinePicture,
    *,
    valid_style_ids: set[int],
) -> None:
    run = ET.SubElement(paragraph_element, _qn(W_NS, "r"))
    _append_run_properties(
        run,
        picture.properties,
        valid_style_ids=valid_style_ids,
    )
    drawing = ET.SubElement(run, _qn(W_NS, "drawing"))
    inline = ET.SubElement(
        drawing,
        _qn(WP_NS, "inline"),
        {"distT": "0", "distB": "0", "distL": "0", "distR": "0"},
    )
    ET.SubElement(
        inline,
        _qn(WP_NS, "extent"),
        {"cx": str(picture.width_emu), "cy": str(picture.height_emu)},
    )
    ET.SubElement(
        inline,
        _qn(WP_NS, "effectExtent"),
        {"l": "0", "t": "0", "r": "0", "b": "0"},
    )
    _append_picture_graphic(
        inline,
        picture,
        width_emu=picture.width_emu,
        height_emu=picture.height_emu,
    )


def _append_embedded_object(
    paragraph_element: ET.Element,
    embedded_object: EmbeddedObject,
    *,
    valid_style_ids: set[int],
) -> None:
    run = ET.SubElement(paragraph_element, _qn(W_NS, "r"))
    _append_run_properties(
        run,
        embedded_object.properties,
        valid_style_ids=valid_style_ids,
    )
    object_element = ET.SubElement(run, _qn(W_NS, "object"))
    shape_id = f"_x0000_i{1024 + embedded_object.object_id}"
    preview = embedded_object.preview
    width_emu = preview.width_emu if preview is not None else 914400
    height_emu = preview.height_emu if preview is not None else 457200
    shape = ET.SubElement(
        object_element,
        _qn(VML_NS, "shape"),
        {
            "id": shape_id,
            "type": "#_x0000_t75",
            "style": (
                f"width:{width_emu / 12700:.2f}pt;"
                f"height:{height_emu / 12700:.2f}pt"
            ),
            _qn(OFFICE_NS, "ole"): "",
        },
    )
    if preview is not None:
        ET.SubElement(
            shape,
            _qn(VML_NS, "imagedata"),
            {
                _qn(R_NS, "id"): f"rIdImage{preview.picture_id}",
                _qn(OFFICE_NS, "title"): "",
            },
        )
    ole_attributes = {
        "Type": "Embed",
        "DrawAspect": "Content",
        "ObjectID": f"_OBJECT_{embedded_object.object_id}",
        "ShapeID": shape_id,
        _qn(R_NS, "id"): f"rIdOleObject{embedded_object.object_id}",
    }
    if embedded_object.prog_id:
        ole_attributes["ProgID"] = embedded_object.prog_id
    ET.SubElement(
        object_element,
        _qn(OFFICE_NS, "OLEObject"),
        ole_attributes,
    )


def _append_floating_picture(
    paragraph_element: ET.Element,
    picture: FloatingPicture,
    *,
    valid_style_ids: set[int],
) -> None:
    width_emu = picture.width_twips * 635
    height_emu = picture.height_twips * 635
    run = ET.SubElement(paragraph_element, _qn(W_NS, "r"))
    _append_run_properties(
        run,
        picture.properties,
        valid_style_ids=valid_style_ids,
    )
    drawing = ET.SubElement(run, _qn(W_NS, "drawing"))
    anchor = ET.SubElement(
        drawing,
        _qn(WP_NS, "anchor"),
        {
            "distT": "0",
            "distB": "0",
            "distL": "0",
            "distR": "0",
            "simplePos": "0",
            "relativeHeight": str(max(picture.shape_id, 1)),
            "behindDoc": "1" if picture.behind_text else "0",
            "locked": "1" if picture.anchor_locked else "0",
            "layoutInCell": "1",
            "allowOverlap": "1",
        },
    )
    ET.SubElement(anchor, _qn(WP_NS, "simplePos"), {"x": "0", "y": "0"})
    horizontal = ET.SubElement(
        anchor,
        _qn(WP_NS, "positionH"),
        {"relativeFrom": picture.horizontal_relative},
    )
    ET.SubElement(horizontal, _qn(WP_NS, "posOffset")).text = str(
        picture.left_twips * 635
    )
    vertical = ET.SubElement(
        anchor,
        _qn(WP_NS, "positionV"),
        {"relativeFrom": picture.vertical_relative},
    )
    ET.SubElement(vertical, _qn(WP_NS, "posOffset")).text = str(
        picture.top_twips * 635
    )
    ET.SubElement(
        anchor,
        _qn(WP_NS, "extent"),
        {"cx": str(width_emu), "cy": str(height_emu)},
    )
    ET.SubElement(
        anchor,
        _qn(WP_NS, "effectExtent"),
        {"l": "0", "t": "0", "r": "0", "b": "0"},
    )
    if picture.wrap_type == "topAndBottom":
        ET.SubElement(anchor, _qn(WP_NS, "wrapTopAndBottom"))
    elif picture.wrap_type == "none":
        ET.SubElement(anchor, _qn(WP_NS, "wrapNone"))
    else:
        wrap_text = {
            "both": "bothSides",
            "left": "left",
            "right": "right",
            "largest": "largest",
        }[picture.wrap_side]
        if picture.wrap_type in ("tight", "through") and picture.wrap_polygon:
            wrap = ET.SubElement(
                anchor,
                _qn(
                    WP_NS,
                    "wrapTight" if picture.wrap_type == "tight" else "wrapThrough",
                ),
                {"wrapText": wrap_text},
            )
            polygon = ET.SubElement(
                wrap,
                _qn(WP_NS, "wrapPolygon"),
                {"edited": "0"},
            )
            first_x, first_y = picture.wrap_polygon[0]
            ET.SubElement(
                polygon,
                _qn(WP_NS, "start"),
                {"x": str(first_x), "y": str(first_y)},
            )
            for x, y in picture.wrap_polygon[1:]:
                ET.SubElement(
                    polygon,
                    _qn(WP_NS, "lineTo"),
                    {"x": str(x), "y": str(y)},
                )
        else:
            ET.SubElement(
                anchor,
                _qn(WP_NS, "wrapSquare"),
                {"wrapText": wrap_text},
            )
    _append_picture_graphic(
        anchor,
        picture,
        width_emu=width_emu,
        height_emu=height_emu,
        rotation_degrees=picture.rotation_degrees,
        flip_horizontal=picture.flip_horizontal,
        flip_vertical=picture.flip_vertical,
    )


def _twips_as_points(value: int) -> str:
    points = value / 20
    return f"{points:.2f}".rstrip("0").rstrip(".")


def _emus_as_points(value: int) -> str:
    points = value / 12700
    return f"{points:.4f}".rstrip("0").rstrip(".")


def _opacity_as_percentage(value: int) -> str:
    percentage = value * 100 / 0x10000
    return f"{percentage:.3f}".rstrip("0").rstrip(".") + "%"


def _append_field(
    paragraph_element: ET.Element,
    field: Field,
    *,
    valid_paragraph_style_ids: set[int],
    valid_character_style_ids: set[int],
) -> None:
    begin_run = ET.SubElement(paragraph_element, _qn(W_NS, "r"))
    _append_run_properties(
        begin_run,
        field.properties,
        valid_style_ids=valid_character_style_ids,
    )
    begin_attributes = {_qn(W_NS, "fldCharType"): "begin"}
    if field.locked:
        begin_attributes[_qn(W_NS, "fldLock")] = "1"
    if field.dirty:
        begin_attributes[_qn(W_NS, "dirty")] = "1"
    ET.SubElement(
        begin_run,
        _qn(W_NS, "fldChar"),
        begin_attributes,
    )
    instruction_run = ET.SubElement(paragraph_element, _qn(W_NS, "r"))
    _append_run_properties(
        instruction_run,
        field.properties,
        valid_style_ids=valid_character_style_ids,
    )
    instruction = ET.SubElement(instruction_run, _qn(W_NS, "instrText"))
    instruction.set(_qn(XML_NS, "space"), "preserve")
    instruction.text = field.instruction
    if field.has_separator:
        separator_run = ET.SubElement(paragraph_element, _qn(W_NS, "r"))
        _append_run_properties(
            separator_run,
            field.properties,
            valid_style_ids=valid_character_style_ids,
        )
        ET.SubElement(
            separator_run,
            _qn(W_NS, "fldChar"),
            {_qn(W_NS, "fldCharType"): "separate"},
        )
        for inline in field.result:
            _append_inline(
                paragraph_element,
                inline,
                valid_paragraph_style_ids=valid_paragraph_style_ids,
                valid_character_style_ids=valid_character_style_ids,
            )
    end_run = ET.SubElement(paragraph_element, _qn(W_NS, "r"))
    _append_run_properties(
        end_run,
        field.properties,
        valid_style_ids=valid_character_style_ids,
    )
    ET.SubElement(
        end_run,
        _qn(W_NS, "fldChar"),
        {_qn(W_NS, "fldCharType"): "end"},
    )


def _append_floating_shape(
    paragraph_element: ET.Element,
    floating_shape: FloatingShape,
    *,
    valid_character_style_ids: set[int],
) -> None:
    horizontal_relative = {
        "margin": "margin",
        "page": "page",
        "column": "text",
    }[floating_shape.horizontal_relative]
    vertical_relative = {
        "margin": "margin",
        "page": "page",
        "paragraph": "text",
    }[floating_shape.vertical_relative]
    style_parts = [
        "position:absolute",
        f"margin-left:{_twips_as_points(floating_shape.left_twips)}pt",
        f"margin-top:{_twips_as_points(floating_shape.top_twips)}pt",
        f"width:{_twips_as_points(floating_shape.width_twips)}pt",
        f"height:{_twips_as_points(floating_shape.height_twips)}pt",
        f"z-index:{-1 if floating_shape.behind_text else 1}",
        f"mso-position-horizontal-relative:{horizontal_relative}",
        f"mso-position-vertical-relative:{vertical_relative}",
    ]
    if floating_shape.flip_horizontal:
        style_parts.append("flip:x")
    if floating_shape.flip_vertical:
        style_parts.append("flip:y")
    if floating_shape.rotation_degrees:
        rotation = f"{floating_shape.rotation_degrees:.4f}".rstrip("0").rstrip(".")
        style_parts.append(f"rotation:{rotation}")
    run = ET.SubElement(paragraph_element, _qn(W_NS, "r"))
    _append_run_properties(
        run,
        floating_shape.properties,
        valid_style_ids=valid_character_style_ids,
    )
    pict = ET.SubElement(run, _qn(W_NS, "pict"))
    shape_style = floating_shape.shape_style or ShapeStyle()
    shape_attributes = {
        "id": f"_x0000_s{floating_shape.shape_id}",
        "style": ";".join(style_parts),
        "stroked": "t" if shape_style.line_enabled else "f",
        "filled": "t" if shape_style.fill_enabled else "f",
        _qn(OFFICE_NS, "allowincell"): "f",
    }
    if shape_style.fill_enabled:
        shape_attributes["fillcolor"] = f"#{shape_style.fill_color}"
    if shape_style.line_enabled:
        shape_attributes["strokecolor"] = f"#{shape_style.line_color}"
        shape_attributes["strokeweight"] = (
            f"{_emus_as_points(shape_style.line_width_emu)}pt"
        )
    if floating_shape.geometry_path is not None:
        element_name, path = "shape", floating_shape.geometry_path
    else:
        element_name, path = _VML_PRESET_SHAPES[floating_shape.shape_type]
    if path is not None:
        shape_attributes["coordsize"] = "21600,21600"
        shape_attributes["path"] = path
    if element_name == "shape":
        shape_attributes[_qn(OFFICE_NS, "spt")] = str(
            floating_shape.shape_type
        )
    shape = ET.SubElement(
        pict,
        _qn(VML_NS, element_name),
        shape_attributes,
    )
    if shape_style.fill_enabled and shape_style.fill_opacity < 0x10000:
        ET.SubElement(
            shape,
            _qn(VML_NS, "fill"),
            {"opacity": _opacity_as_percentage(shape_style.fill_opacity)},
        )
    stroke_attributes: dict[str, str] = {}
    if shape_style.line_enabled:
        if shape_style.line_opacity < 0x10000:
            stroke_attributes["opacity"] = _opacity_as_percentage(
                shape_style.line_opacity
            )
        if shape_style.line_style != "single":
            stroke_attributes["linestyle"] = shape_style.line_style
        if shape_style.line_dash != "solid":
            stroke_attributes["dashstyle"] = shape_style.line_dash
        if shape_style.line_join != "round":
            stroke_attributes["joinstyle"] = shape_style.line_join
        if shape_style.line_end_cap != "flat":
            stroke_attributes["endcap"] = shape_style.line_end_cap
    if stroke_attributes:
        ET.SubElement(shape, _qn(VML_NS, "stroke"), stroke_attributes)
    ET.SubElement(
        shape,
        _qn(WORD_2003_NS, "wrap"),
        {"type": floating_shape.wrap_type, "side": floating_shape.wrap_side},
    )
    if floating_shape.anchor_locked:
        ET.SubElement(
            shape,
            _qn(OFFICE_NS, "lock"),
            {_qn(VML_NS, "ext"): "edit", "position": "t"},
        )


def _append_floating_textbox(
    paragraph_element: ET.Element,
    textbox: FloatingTextBox,
    *,
    valid_paragraph_style_ids: set[int],
    valid_character_style_ids: set[int],
) -> None:
    horizontal_relative = {
        "margin": "margin",
        "page": "page",
        "column": "text",
    }[textbox.horizontal_relative]
    vertical_relative = {
        "margin": "margin",
        "page": "page",
        "paragraph": "text",
    }[textbox.vertical_relative]
    style_parts = [
            "position:absolute",
            f"margin-left:{_twips_as_points(textbox.left_twips)}pt",
            f"margin-top:{_twips_as_points(textbox.top_twips)}pt",
            f"width:{_twips_as_points(textbox.width_twips)}pt",
            f"height:{_twips_as_points(textbox.height_twips)}pt",
            f"z-index:{-1 if textbox.behind_text else 1}",
            f"mso-position-horizontal-relative:{horizontal_relative}",
            f"mso-position-vertical-relative:{vertical_relative}",
    ]
    if textbox.flip_horizontal:
        style_parts.append("flip:x")
    if textbox.flip_vertical:
        style_parts.append("flip:y")
    if textbox.rotation_degrees:
        rotation = f"{textbox.rotation_degrees:.4f}".rstrip("0").rstrip(".")
        style_parts.append(f"rotation:{rotation}")
    style = ";".join(style_parts)
    run = ET.SubElement(paragraph_element, _qn(W_NS, "r"))
    pict = ET.SubElement(run, _qn(W_NS, "pict"))
    shape_style = textbox.shape_style
    shape_attributes = {
        "id": f"_x0000_s{textbox.shape_id}",
        "style": style,
        "stroked": "t" if shape_style and shape_style.line_enabled else "f",
        "filled": "t" if shape_style and shape_style.fill_enabled else "f",
        _qn(OFFICE_NS, "allowincell"): "f",
    }
    if shape_style is not None and shape_style.fill_enabled:
        shape_attributes["fillcolor"] = f"#{shape_style.fill_color}"
    if shape_style is not None and shape_style.line_enabled:
        shape_attributes["strokecolor"] = f"#{shape_style.line_color}"
        shape_attributes["strokeweight"] = (
            f"{_emus_as_points(shape_style.line_width_emu)}pt"
        )
    shape = ET.SubElement(
        pict,
        _qn(VML_NS, "rect"),
        shape_attributes,
    )
    if (
        shape_style is not None
        and shape_style.fill_enabled
        and shape_style.fill_opacity < 0x10000
    ):
        ET.SubElement(
            shape,
            _qn(VML_NS, "fill"),
            {"opacity": _opacity_as_percentage(shape_style.fill_opacity)},
        )
    stroke_attributes: dict[str, str] = {}
    if shape_style is not None and shape_style.line_enabled:
        if shape_style.line_opacity < 0x10000:
            stroke_attributes["opacity"] = _opacity_as_percentage(
                shape_style.line_opacity
            )
        if shape_style.line_style != "single":
            stroke_attributes["linestyle"] = shape_style.line_style
        if shape_style.line_dash != "solid":
            stroke_attributes["dashstyle"] = shape_style.line_dash
        if shape_style.line_join != "round":
            stroke_attributes["joinstyle"] = shape_style.line_join
        if shape_style.line_end_cap != "flat":
            stroke_attributes["endcap"] = shape_style.line_end_cap
    if stroke_attributes:
        ET.SubElement(
            shape,
            _qn(VML_NS, "stroke"),
            stroke_attributes,
        )
    ET.SubElement(
        shape,
        _qn(WORD_2003_NS, "wrap"),
        {"type": textbox.wrap_type, "side": textbox.wrap_side},
    )
    if textbox.anchor_locked:
        ET.SubElement(
            shape,
            _qn(OFFICE_NS, "lock"),
            {_qn(VML_NS, "ext"): "edit", "position": "t"},
        )
    inset = "0,0,0,0"
    if shape_style is not None:
        inset = ",".join(
            f"{_emus_as_points(value)}pt"
            for value in (
                shape_style.inset_left_emu,
                shape_style.inset_top_emu,
                shape_style.inset_right_emu,
                shape_style.inset_bottom_emu,
            )
        )
    vml_textbox = ET.SubElement(
        shape,
        _qn(VML_NS, "textbox"),
        {"inset": inset},
    )
    content = ET.SubElement(vml_textbox, _qn(W_NS, "txbxContent"))
    for block in textbox.body_blocks or (Paragraph(()),):
        if isinstance(block, Paragraph):
            _append_paragraph(
                content,
                block,
                valid_paragraph_style_ids=valid_paragraph_style_ids,
                valid_character_style_ids=valid_character_style_ids,
            )
        elif isinstance(block, Table):
            _append_table(
                content,
                block,
                valid_paragraph_style_ids=valid_paragraph_style_ids,
                valid_character_style_ids=valid_character_style_ids,
            )
    if textbox.body_blocks and isinstance(textbox.body_blocks[-1], Table):
        _append_paragraph(
            content,
            Paragraph(()),
            valid_paragraph_style_ids=valid_paragraph_style_ids,
            valid_character_style_ids=valid_character_style_ids,
        )


def _append_inline(
    paragraph_element: ET.Element,
    inline: (
        TextRun
        | Symbol
        | Tab
        | NoBreakHyphen
        | SoftHyphen
        | SeparatorMark
        | ContinuationSeparatorMark
        | Break
        | Field
        | BookmarkStart
        | BookmarkEnd
        | FootnoteReference
        | EndnoteReference
        | CommentRangeStart
        | CommentRangeEnd
        | CommentReference
        | InlinePicture
        | EmbeddedObject
        | FloatingPicture
        | FloatingShape
        | FloatingTextBox
    ),
    *,
    valid_paragraph_style_ids: set[int],
    valid_character_style_ids: set[int],
) -> None:
    if isinstance(inline, TextRun):
        _append_text_run(
            paragraph_element,
            inline.text,
            inline.properties,
            valid_style_ids=valid_character_style_ids,
        )
    elif isinstance(inline, Symbol):
        _append_symbol(
            paragraph_element,
            inline,
            valid_style_ids=valid_character_style_ids,
        )
    elif isinstance(inline, InlinePicture):
        _append_inline_picture(
            paragraph_element,
            inline,
            valid_style_ids=valid_character_style_ids,
        )
    elif isinstance(inline, EmbeddedObject):
        _append_embedded_object(
            paragraph_element,
            inline,
            valid_style_ids=valid_character_style_ids,
        )
    elif isinstance(inline, FloatingPicture):
        _append_floating_picture(
            paragraph_element,
            inline,
            valid_style_ids=valid_character_style_ids,
        )
    elif isinstance(inline, FloatingShape):
        _append_floating_shape(
            paragraph_element,
            inline,
            valid_character_style_ids=valid_character_style_ids,
        )
    elif isinstance(inline, Tab):
        run = ET.SubElement(paragraph_element, _qn(W_NS, "r"))
        _append_run_properties(
            run,
            inline.properties,
            valid_style_ids=valid_character_style_ids,
        )
        ET.SubElement(run, _qn(W_NS, "tab"))
    elif isinstance(inline, (NoBreakHyphen, SoftHyphen)):
        run = ET.SubElement(paragraph_element, _qn(W_NS, "r"))
        _append_run_properties(
            run,
            inline.properties,
            valid_style_ids=valid_character_style_ids,
        )
        ET.SubElement(
            run,
            _qn(
                W_NS,
                "noBreakHyphen"
                if isinstance(inline, NoBreakHyphen)
                else "softHyphen",
            ),
        )
    elif isinstance(inline, (SeparatorMark, ContinuationSeparatorMark)):
        run = ET.SubElement(paragraph_element, _qn(W_NS, "r"))
        _append_run_properties(
            run,
            inline.properties,
            valid_style_ids=valid_character_style_ids,
        )
        ET.SubElement(
            run,
            _qn(
                W_NS,
                "separator"
                if isinstance(inline, SeparatorMark)
                else "continuationSeparator",
            ),
        )
    elif isinstance(inline, Break):
        run = ET.SubElement(paragraph_element, _qn(W_NS, "r"))
        _append_run_properties(
            run,
            inline.properties,
            valid_style_ids=valid_character_style_ids,
        )
        attributes = (
            {_qn(W_NS, "type"): "page"}
            if inline.kind is BreakType.PAGE
            else {}
        )
        if (
            inline.kind is BreakType.LINE
            and inline.properties.line_break_clear is not None
        ):
            attributes[_qn(W_NS, "clear")] = (
                inline.properties.line_break_clear
            )
        ET.SubElement(run, _qn(W_NS, "br"), attributes)
    elif isinstance(inline, Field):
        _append_field(
            paragraph_element,
            inline,
            valid_paragraph_style_ids=valid_paragraph_style_ids,
            valid_character_style_ids=valid_character_style_ids,
        )
    elif isinstance(inline, (BookmarkStart, BookmarkEnd)):
        attributes = {_qn(W_NS, "id"): str(inline.bookmark_id)}
        if isinstance(inline, BookmarkStart):
            attributes[_qn(W_NS, "name")] = inline.name
            if inline.column_first is not None and inline.column_last is not None:
                attributes[_qn(W_NS, "colFirst")] = str(inline.column_first)
                attributes[_qn(W_NS, "colLast")] = str(inline.column_last)
        ET.SubElement(
            paragraph_element,
            _qn(
                W_NS,
                "bookmarkStart" if isinstance(inline, BookmarkStart) else "bookmarkEnd",
            ),
            attributes,
        )
    elif isinstance(inline, (FootnoteReference, EndnoteReference)):
        run = ET.SubElement(paragraph_element, _qn(W_NS, "r"))
        _append_run_properties(
            run,
            inline.properties,
            valid_style_ids=valid_character_style_ids,
        )
        run_properties = run.find(_qn(W_NS, "rPr"))
        if run_properties is None:
            run_properties = ET.Element(_qn(W_NS, "rPr"))
            run.insert(0, run_properties)
        vertical_align = run_properties.find(_qn(W_NS, "vertAlign"))
        if vertical_align is None:
            vertical_align = ET.SubElement(
                run_properties,
                _qn(W_NS, "vertAlign"),
            )
        vertical_align.set(_qn(W_NS, "val"), "superscript")
        reference_attributes = {
            _qn(W_NS, "id"): str(
                inline.footnote_id
                if isinstance(inline, FootnoteReference)
                else inline.endnote_id
            )
        }
        if inline.custom_mark is not None:
            reference_attributes[_qn(W_NS, "customMarkFollows")] = "1"
        ET.SubElement(
            run,
            _qn(
                W_NS,
                "footnoteReference"
                if isinstance(inline, FootnoteReference)
                else "endnoteReference",
            ),
            reference_attributes,
        )
        if inline.custom_mark is not None:
            mark_run = ET.SubElement(paragraph_element, _qn(W_NS, "r"))
            _append_run_properties(
                mark_run,
                inline.properties,
                valid_style_ids=valid_character_style_ids,
            )
            mark_properties = mark_run.find(_qn(W_NS, "rPr"))
            if mark_properties is None:
                mark_properties = ET.Element(_qn(W_NS, "rPr"))
                mark_run.insert(0, mark_properties)
            mark_align = mark_properties.find(_qn(W_NS, "vertAlign"))
            if mark_align is None:
                mark_align = ET.SubElement(
                    mark_properties,
                    _qn(W_NS, "vertAlign"),
                )
            mark_align.set(_qn(W_NS, "val"), "superscript")
            mark_text = ET.SubElement(mark_run, _qn(W_NS, "t"))
            mark_text.text = inline.custom_mark
    elif isinstance(inline, (CommentRangeStart, CommentRangeEnd)):
        ET.SubElement(
            paragraph_element,
            _qn(
                W_NS,
                "commentRangeStart"
                if isinstance(inline, CommentRangeStart)
                else "commentRangeEnd",
            ),
            {_qn(W_NS, "id"): str(inline.comment_id)},
        )
    elif isinstance(inline, CommentReference):
        run = ET.SubElement(paragraph_element, _qn(W_NS, "r"))
        _append_run_properties(
            run,
            inline.properties,
            valid_style_ids=valid_character_style_ids,
        )
        run_properties = run.find(_qn(W_NS, "rPr"))
        if run_properties is None:
            run_properties = ET.Element(_qn(W_NS, "rPr"))
            run.insert(0, run_properties)
        ET.SubElement(
            run_properties,
            _qn(W_NS, "vertAlign"),
            {_qn(W_NS, "val"): "superscript"},
        )
        ET.SubElement(
            run,
            _qn(W_NS, "commentReference"),
            {_qn(W_NS, "id"): str(inline.comment_id)},
        )
    elif isinstance(inline, FloatingTextBox):
        _append_floating_textbox(
            paragraph_element,
            inline,
            valid_paragraph_style_ids=valid_paragraph_style_ids,
            valid_character_style_ids=valid_character_style_ids,
        )


def _append_section_properties(
    parent: ET.Element,
    section: SectionProperties,
    *,
    include_break_type: bool,
    header_footer_parts: tuple[_HeaderFooterPart, ...] = (),
) -> None:
    section_attributes = {}
    if section.revision_save_id is not None:
        section_attributes[_qn(W_NS, "rsidSect")] = (
            f"{section.revision_save_id:08X}"
        )
    section_properties = ET.SubElement(
        parent,
        _qn(W_NS, "sectPr"),
        section_attributes,
    )
    for part in header_footer_parts:
        ET.SubElement(
            section_properties,
            _qn(W_NS, f"{part.kind}Reference"),
            {
                _qn(W_NS, "type"): part.reference_type,
                _qn(R_NS, "id"): part.relationship_id,
            },
        )
    if (
        section.footnote_position is not None
        or section.footnote_number_format is not None
        or section.footnote_number_start is not None
        or section.footnote_number_restart is not None
    ):
        footnote_properties = ET.SubElement(
            section_properties,
            _qn(W_NS, "footnotePr"),
        )
        if section.footnote_position is not None:
            ET.SubElement(
                footnote_properties,
                _qn(W_NS, "pos"),
                {_qn(W_NS, "val"): section.footnote_position},
            )
        if section.footnote_number_format is not None:
            ET.SubElement(
                footnote_properties,
                _qn(W_NS, "numFmt"),
                {_qn(W_NS, "val"): section.footnote_number_format},
            )
        if section.footnote_number_start is not None:
            ET.SubElement(
                footnote_properties,
                _qn(W_NS, "numStart"),
                {_qn(W_NS, "val"): str(section.footnote_number_start)},
            )
        if section.footnote_number_restart is not None:
            ET.SubElement(
                footnote_properties,
                _qn(W_NS, "numRestart"),
                {_qn(W_NS, "val"): section.footnote_number_restart},
            )
    if (
        section.endnote_position is not None
        or section.endnote_number_format is not None
        or section.endnote_number_start is not None
        or section.endnote_number_restart is not None
    ):
        endnote_properties = ET.SubElement(
            section_properties,
            _qn(W_NS, "endnotePr"),
        )
        if section.endnote_position is not None:
            ET.SubElement(
                endnote_properties,
                _qn(W_NS, "pos"),
                {_qn(W_NS, "val"): section.endnote_position},
            )
        if section.endnote_number_format is not None:
            ET.SubElement(
                endnote_properties,
                _qn(W_NS, "numFmt"),
                {_qn(W_NS, "val"): section.endnote_number_format},
            )
        if section.endnote_number_start is not None:
            ET.SubElement(
                endnote_properties,
                _qn(W_NS, "numStart"),
                {_qn(W_NS, "val"): str(section.endnote_number_start)},
            )
        if section.endnote_number_restart is not None:
            ET.SubElement(
                endnote_properties,
                _qn(W_NS, "numRestart"),
                {_qn(W_NS, "val"): section.endnote_number_restart},
            )
    if include_break_type:
        ET.SubElement(
            section_properties,
            _qn(W_NS, "type"),
            {_qn(W_NS, "val"): section.break_type.value},
        )
    ET.SubElement(
        section_properties,
        _qn(W_NS, "pgSz"),
        {
            _qn(W_NS, "w"): str(section.page_width_twips),
            _qn(W_NS, "h"): str(section.page_height_twips),
            _qn(W_NS, "orient"): section.orientation,
        },
    )
    ET.SubElement(
        section_properties,
        _qn(W_NS, "pgMar"),
        {
            _qn(W_NS, "top"): str(section.margin_top_twips),
            _qn(W_NS, "right"): str(section.margin_right_twips),
            _qn(W_NS, "bottom"): str(section.margin_bottom_twips),
            _qn(W_NS, "left"): str(section.margin_left_twips),
            _qn(W_NS, "header"): str(section.header_distance_twips),
            _qn(W_NS, "footer"): str(section.footer_distance_twips),
            _qn(W_NS, "gutter"): str(section.gutter_twips),
        },
    )
    if (
        section.paper_source_first is not None
        or section.paper_source_other is not None
    ):
        paper_source_attributes = {}
        if section.paper_source_first is not None:
            paper_source_attributes[_qn(W_NS, "first")] = str(
                section.paper_source_first
            )
        if section.paper_source_other is not None:
            paper_source_attributes[_qn(W_NS, "other")] = str(
                section.paper_source_other
            )
        ET.SubElement(
            section_properties,
            _qn(W_NS, "paperSrc"),
            paper_source_attributes,
        )
    if section.page_borders is not None:
        page_border_attributes = {}
        if section.page_border_display is not None:
            page_border_attributes[_qn(W_NS, "display")] = (
                section.page_border_display
            )
        if section.page_border_offset_from is not None:
            page_border_attributes[_qn(W_NS, "offsetFrom")] = (
                section.page_border_offset_from
            )
        if section.page_border_z_order is not None:
            page_border_attributes[_qn(W_NS, "zOrder")] = (
                section.page_border_z_order
            )
        page_borders = ET.SubElement(
            section_properties,
            _qn(W_NS, "pgBorders"),
            page_border_attributes,
        )
        for name, border in (
            ("top", section.page_borders.top),
            ("left", section.page_borders.left),
            ("bottom", section.page_borders.bottom),
            ("right", section.page_borders.right),
        ):
            if border is not None:
                ET.SubElement(
                    page_borders,
                    _qn(W_NS, name),
                    _border_attributes(border),
                )
    if (
        section.page_number_format is not None
        or section.page_number_start is not None
        or section.page_number_chapter_style is not None
    ):
        page_number_attributes = {}
        if section.page_number_format is not None:
            page_number_attributes[_qn(W_NS, "fmt")] = (
                section.page_number_format
            )
        if section.page_number_start is not None:
            page_number_attributes[_qn(W_NS, "start")] = str(
                section.page_number_start
            )
        if section.page_number_chapter_style is not None:
            page_number_attributes[_qn(W_NS, "chapStyle")] = str(
                section.page_number_chapter_style
            )
        if section.page_number_chapter_separator is not None:
            page_number_attributes[_qn(W_NS, "chapSep")] = (
                section.page_number_chapter_separator
            )
        ET.SubElement(
            section_properties,
            _qn(W_NS, "pgNumType"),
            page_number_attributes,
        )
    if section.line_number_count_by is not None:
        line_number_attributes = {
            _qn(W_NS, "countBy"): str(section.line_number_count_by),
        }
        if section.line_number_start is not None:
            line_number_attributes[_qn(W_NS, "start")] = str(
                section.line_number_start
            )
        if section.line_number_distance_twips is not None:
            line_number_attributes[_qn(W_NS, "distance")] = str(
                section.line_number_distance_twips
            )
        if section.line_number_restart is not None:
            line_number_attributes[_qn(W_NS, "restart")] = (
                section.line_number_restart
            )
        ET.SubElement(
            section_properties,
            _qn(W_NS, "lnNumType"),
            line_number_attributes,
        )
    column_attributes: dict[str, str] = {}
    if section.column_count is not None:
        column_attributes[_qn(W_NS, "num")] = str(section.column_count)
    if section.column_spacing_twips is not None:
        column_attributes[_qn(W_NS, "space")] = str(
            section.column_spacing_twips
        )
    if section.columns_evenly_spaced is not None:
        column_attributes[_qn(W_NS, "equalWidth")] = (
            "1" if section.columns_evenly_spaced else "0"
        )
    if section.column_separator is not None:
        column_attributes[_qn(W_NS, "sep")] = (
            "1" if section.column_separator else "0"
        )
    columns_element: ET.Element | None = None
    if column_attributes or section.column_widths_twips is not None:
        columns_element = ET.SubElement(
            section_properties,
            _qn(W_NS, "cols"),
            column_attributes,
        )
    if columns_element is not None and section.column_widths_twips is not None:
        spacings = section.column_spacings_twips or ()
        for index, width in enumerate(section.column_widths_twips):
            attributes = {_qn(W_NS, "w"): str(width)}
            if index < len(spacings):
                attributes[_qn(W_NS, "space")] = str(spacings[index])
            ET.SubElement(columns_element, _qn(W_NS, "col"), attributes)
    _append_boolean_property(
        section_properties,
        "formProt",
        section.form_protected,
    )
    if section.vertical_alignment is not None:
        ET.SubElement(
            section_properties,
            _qn(W_NS, "vAlign"),
            {_qn(W_NS, "val"): section.vertical_alignment},
        )
    if section.suppress_endnotes:
        ET.SubElement(section_properties, _qn(W_NS, "noEndnote"))
    if section.title_page:
        ET.SubElement(section_properties, _qn(W_NS, "titlePg"))
    if section.text_direction is not None:
        ET.SubElement(
            section_properties,
            _qn(W_NS, "textDirection"),
            {_qn(W_NS, "val"): section.text_direction},
        )
    _append_boolean_property(
        section_properties,
        "bidi",
        section.bidirectional,
    )
    _append_boolean_property(
        section_properties,
        "rtlGutter",
        section.rtl_gutter,
    )
    if (
        section.document_grid_type is not None
        and section.document_grid_line_pitch_twips is not None
    ):
        attributes = {
            _qn(W_NS, "type"): section.document_grid_type,
            _qn(W_NS, "linePitch"): str(
                section.document_grid_line_pitch_twips
            ),
        }
        if section.document_grid_character_space is not None:
            attributes[_qn(W_NS, "charSpace")] = str(
                section.document_grid_character_space
            )
        ET.SubElement(section_properties, _qn(W_NS, "docGrid"), attributes)


def _append_paragraph(
    parent: ET.Element,
    paragraph: Paragraph,
    *,
    valid_paragraph_style_ids: set[int],
    valid_character_style_ids: set[int],
    section_references: dict[
        tuple[int, int], tuple[_HeaderFooterPart, ...]
    ] | None = None,
) -> None:
    paragraph_attributes = {}
    if paragraph.properties.revision_save_id is not None:
        paragraph_attributes[_qn(W_NS, "rsidP")] = (
            f"{paragraph.properties.revision_save_id:08X}"
        )
    paragraph_element = ET.SubElement(
        parent,
        _qn(W_NS, "p"),
        paragraph_attributes,
    )
    _append_paragraph_properties(
        paragraph_element,
        paragraph.properties,
        valid_style_ids=valid_paragraph_style_ids,
        mark_properties=paragraph.mark_properties,
        valid_mark_style_ids=valid_character_style_ids,
    )
    if paragraph.section_end is not None:
        paragraph_properties = paragraph_element.find(_qn(W_NS, "pPr"))
        if paragraph_properties is None:
            paragraph_properties = ET.Element(_qn(W_NS, "pPr"))
            paragraph_element.insert(0, paragraph_properties)
        _append_section_properties(
            paragraph_properties,
            paragraph.section_end,
            include_break_type=True,
            header_footer_parts=(section_references or {}).get(
                (
                    paragraph.section_end.cp_start,
                    paragraph.section_end.cp_end,
                ),
                (),
            ),
        )
    for inline in paragraph.inlines:
        _append_inline(
            paragraph_element,
            inline,
            valid_paragraph_style_ids=valid_paragraph_style_ids,
            valid_character_style_ids=valid_character_style_ids,
        )


def _border_attributes(border: BorderProperties) -> dict[str, str]:
    attributes = {
        _qn(W_NS, "val"): border.style,
        _qn(W_NS, "sz"): str(border.size_eighth_points),
        _qn(W_NS, "color"): border.color,
        _qn(W_NS, "space"): str(border.space_points),
    }
    if border.shadow:
        attributes[_qn(W_NS, "shadow")] = "1"
    if border.frame:
        attributes[_qn(W_NS, "frame")] = "1"
    return attributes


def _append_borders(
    parent: ET.Element,
    container_name: str,
    borders: TableBorders,
    *,
    include_inside: bool,
) -> None:
    values = (
        ("top", borders.top),
        ("left", borders.left),
        ("bottom", borders.bottom),
        ("right", borders.right),
    )
    if include_inside:
        values += (
            ("insideH", borders.inside_horizontal),
            ("insideV", borders.inside_vertical),
        )
    if container_name == "tcBorders":
        values += (
            ("tl2br", borders.diagonal_down),
            ("tr2bl", borders.diagonal_up),
        )
    elif container_name == "pBdr":
        values += (("between", borders.between),)
    if not any(border is not None for _, border in values):
        return
    container = ET.SubElement(parent, _qn(W_NS, container_name))
    for name, border in values:
        if border is not None:
            ET.SubElement(
                container,
                _qn(W_NS, name),
                _border_attributes(border),
            )


def _append_cell_margins(
    parent: ET.Element,
    margins: TableCellMargins,
    *,
    container_name: str = "tcMar",
) -> None:
    values = (
        ("top", margins.top),
        ("left", margins.left),
        ("bottom", margins.bottom),
        ("right", margins.right),
    )
    if not any(value is not None for _, value in values):
        return
    container = ET.SubElement(parent, _qn(W_NS, container_name))
    for side, value in values:
        if value is not None:
            ET.SubElement(
                container,
                _qn(W_NS, side),
                {
                    _qn(W_NS, "w"): str(value),
                    _qn(W_NS, "type"): "dxa",
                },
            )


def _append_shading(
    parent: ET.Element,
    shading: ShadingProperties | None,
) -> None:
    if shading is None:
        return
    ET.SubElement(
        parent,
        _qn(W_NS, "shd"),
        {
            _qn(W_NS, "val"): shading.pattern,
            _qn(W_NS, "color"): shading.foreground,
            _qn(W_NS, "fill"): shading.background,
        },
    )


def _append_table_property_elements(
    parent: ET.Element,
    properties: TableRowProperties,
    *,
    include_width: bool,
) -> None:
    positioning_attributes: dict[str, str] = {}
    for name, value in (
        ("horzAnchor", properties.horizontal_anchor),
        ("vertAnchor", properties.vertical_anchor),
        ("tblpX", properties.horizontal_position_twips),
        ("tblpXSpec", properties.horizontal_alignment),
        ("tblpY", properties.vertical_position_twips),
        ("tblpYSpec", properties.vertical_alignment),
        ("leftFromText", properties.distance_left_twips),
        ("rightFromText", properties.distance_right_twips),
        ("topFromText", properties.distance_top_twips),
        ("bottomFromText", properties.distance_bottom_twips),
    ):
        if value is not None:
            positioning_attributes[_qn(W_NS, name)] = str(value)
    if positioning_attributes:
        ET.SubElement(
            parent,
            _qn(W_NS, "tblpPr"),
            positioning_attributes,
        )
    if properties.no_overlap is not None:
        ET.SubElement(
            parent,
            _qn(W_NS, "tblOverlap"),
            {
                _qn(W_NS, "val"): (
                    "never" if properties.no_overlap else "overlap"
                )
            },
        )
    _append_boolean_property(parent, "bidiVisual", properties.bidirectional)
    if properties.row_band_size is not None:
        ET.SubElement(
            parent,
            _qn(W_NS, "tblStyleRowBandSize"),
            {_qn(W_NS, "val"): str(properties.row_band_size)},
        )
    if properties.column_band_size is not None:
        ET.SubElement(
            parent,
            _qn(W_NS, "tblStyleColBandSize"),
            {_qn(W_NS, "val"): str(properties.column_band_size)},
        )
    if include_width or properties.preferred_width_type is not None:
        width_type = properties.preferred_width_type or "auto"
        width = properties.preferred_width or 0
        ET.SubElement(
            parent,
            _qn(W_NS, "tblW"),
            {
                _qn(W_NS, "w"): str(width),
                _qn(W_NS, "type"): width_type,
            },
        )
    if properties.alignment is not None:
        ET.SubElement(
            parent,
            _qn(W_NS, "jc"),
            {_qn(W_NS, "val"): properties.alignment},
        )
    indent = properties.left_indent_twips
    if indent is None and properties.gap_half_twips is not None:
        # WordprocessingML's tblInd is measured from the text margin;
        # unlike DOC's table origin it must not subtract dxaGapHalf again.
        indent = 0
    if indent is not None:
        ET.SubElement(
            parent,
            _qn(W_NS, "tblInd"),
            {
                _qn(W_NS, "w"): str(indent),
                _qn(W_NS, "type"): "dxa",
            },
        )
    _append_borders(
        parent,
        "tblBorders",
        properties.borders,
        include_inside=True,
    )
    _append_shading(parent, properties.table_shading)
    if properties.auto_fit is not None:
        ET.SubElement(
            parent,
            _qn(W_NS, "tblLayout"),
            {
                _qn(W_NS, "type"): (
                    "autofit" if properties.auto_fit else "fixed"
                )
            },
        )
    _append_cell_margins(
        parent,
        properties.default_cell_margins,
        container_name="tblCellMar",
    )
    table_look = {
        _qn(W_NS, "firstRow"): properties.first_row_style,
        _qn(W_NS, "lastRow"): properties.last_row_style,
        _qn(W_NS, "firstColumn"): properties.first_column_style,
        _qn(W_NS, "lastColumn"): properties.last_column_style,
        _qn(W_NS, "noHBand"): properties.no_row_banding,
        _qn(W_NS, "noVBand"): properties.no_column_banding,
    }
    if any(value is not None for value in table_look.values()):
        ET.SubElement(
            parent,
            _qn(W_NS, "tblLook"),
            {
                name: "1" if value else "0"
                for name, value in table_look.items()
                if value is not None
            },
        )


def _append_table_style_cell_properties(
    parent: ET.Element,
    properties: TableRowProperties,
) -> None:
    if (
        properties.style_cell_borders == TableBorders()
        and properties.style_cell_shading is None
        and properties.style_cell_vertical_alignment is None
        and properties.style_cell_no_wrap is None
    ):
        return
    cell_properties = ET.SubElement(parent, _qn(W_NS, "tcPr"))
    _append_borders(
        cell_properties,
        "tcBorders",
        properties.style_cell_borders,
        include_inside=True,
    )
    _append_shading(cell_properties, properties.style_cell_shading)
    _append_boolean_property(
        cell_properties,
        "noWrap",
        properties.style_cell_no_wrap,
    )
    if properties.style_cell_vertical_alignment is not None:
        ET.SubElement(
            cell_properties,
            _qn(W_NS, "vAlign"),
            {_qn(W_NS, "val"): properties.style_cell_vertical_alignment},
        )


def _append_table_cell(
    row_element: ET.Element,
    cell: TableCell,
    *,
    valid_paragraph_style_ids: set[int],
    valid_character_style_ids: set[int],
    valid_table_style_ids: set[int],
) -> None:
    cell_element = ET.SubElement(row_element, _qn(W_NS, "tc"))
    has_properties = (
        cell.width_twips is not None
        or cell.grid_span > 1
        or cell.vertical_merge is not None
        or cell.text_direction is not None
        or cell.vertical_alignment is not None
        or cell.fit_text is not None
        or cell.no_wrap is not None
        or cell.hide_mark is not None
        or cell.borders != TableBorders()
        or cell.margins != TableCellMargins()
        or cell.shading is not None
    )
    if has_properties:
        properties = ET.SubElement(cell_element, _qn(W_NS, "tcPr"))
        if cell.width_twips is not None:
            ET.SubElement(
                properties,
                _qn(W_NS, "tcW"),
                {
                    _qn(W_NS, "w"): str(cell.width_twips),
                    _qn(W_NS, "type"): "dxa",
                },
            )
        if cell.grid_span > 1:
            ET.SubElement(
                properties,
                _qn(W_NS, "gridSpan"),
                {_qn(W_NS, "val"): str(cell.grid_span)},
            )
        if cell.vertical_merge is not None:
            ET.SubElement(
                properties,
                _qn(W_NS, "vMerge"),
                {_qn(W_NS, "val"): cell.vertical_merge},
            )
        if cell.text_direction is not None:
            ET.SubElement(
                properties,
                _qn(W_NS, "textDirection"),
                {_qn(W_NS, "val"): cell.text_direction},
            )
        _append_borders(
            properties,
            "tcBorders",
            cell.borders,
            include_inside=False,
        )
        _append_shading(properties, cell.shading)
        _append_boolean_property(properties, "noWrap", cell.no_wrap)
        _append_cell_margins(properties, cell.margins)
        _append_boolean_property(properties, "tcFitText", cell.fit_text)
        _append_boolean_property(properties, "hideMark", cell.hide_mark)
        if cell.vertical_alignment is not None:
            ET.SubElement(
                properties,
                _qn(W_NS, "vAlign"),
                {_qn(W_NS, "val"): cell.vertical_alignment},
            )
    content = cell.body_blocks or (Paragraph(()),)
    for block in content:
        if isinstance(block, Paragraph):
            _append_paragraph(
                cell_element,
                block,
                valid_paragraph_style_ids=valid_paragraph_style_ids,
                valid_character_style_ids=valid_character_style_ids,
            )
        elif isinstance(block, Table):
            _append_table(
                cell_element,
                block,
                valid_paragraph_style_ids=valid_paragraph_style_ids,
                valid_character_style_ids=valid_character_style_ids,
            )
    if isinstance(content[-1], Table):
        _append_paragraph(
            cell_element,
            Paragraph(()),
            valid_paragraph_style_ids=valid_paragraph_style_ids,
            valid_character_style_ids=valid_character_style_ids,
        )


def _normalized_floating_table_properties(
    properties: TableRowProperties,
) -> TableRowProperties:
    """Stabilize a floating DOC table with an explicit grid in OOXML.

    Legacy producers can store a percentage preferred width alongside an
    authoritative absolute TDefTable grid.  Carrying both into an autofit
    floating WordprocessingML table lets consumers rescale and shift the grid.
    Prefer the concrete grid for this combination, matching Word's normalized
    representation of the same binary table.
    """

    boundaries = properties.cell_boundaries_twips
    is_floating = (
        properties.horizontal_anchor is not None
        or properties.vertical_anchor is not None
    )
    if (
        not is_floating
        or properties.preferred_width_type != "pct"
        or len(boundaries) < 2
    ):
        return properties
    grid_width = max(boundaries) - min(boundaries)
    if grid_width <= 0:
        return properties
    return replace(
        properties,
        preferred_width=grid_width,
        preferred_width_type="dxa",
        auto_fit=False,
        left_indent_twips=max(-min(boundaries), 0),
        horizontal_position_twips=(
            0
            if properties.horizontal_position_twips is None
            and properties.horizontal_alignment is None
            else properties.horizontal_position_twips
        ),
    )


def _append_table(
    body: ET.Element,
    table: Table,
    *,
    valid_paragraph_style_ids: set[int],
    valid_character_style_ids: set[int],
    valid_table_style_ids: set[int] | None = None,
) -> None:
    table_element = ET.SubElement(body, _qn(W_NS, "tbl"))
    first_properties = table.rows[0].properties if table.rows else None
    if first_properties is not None:
        first_properties = _normalized_floating_table_properties(first_properties)
        table_properties = ET.SubElement(table_element, _qn(W_NS, "tblPr"))
        if (
            first_properties.table_style_id is not None
            and valid_table_style_ids is not None
            and first_properties.table_style_id in valid_table_style_ids
        ):
            ET.SubElement(
                table_properties,
                _qn(W_NS, "tblStyle"),
                {_qn(W_NS, "val"): f"DocStyle{first_properties.table_style_id}"},
            )
        _append_table_property_elements(
            table_properties,
            first_properties,
            include_width=True,
        )

    grid = ET.SubElement(table_element, _qn(W_NS, "tblGrid"))
    shared_boundaries: set[int] = set()
    for row in table.rows:
        row_boundaries = row.properties.cell_boundaries_twips
        shared_boundaries.update(row_boundaries)
        if row_boundaries:
            if row.properties.grid_before_width:
                shared_boundaries.add(
                    row_boundaries[0] - row.properties.grid_before_width
                )
            if row.properties.grid_after_width:
                shared_boundaries.add(
                    row_boundaries[-1] + row.properties.grid_after_width
                )
    boundaries = tuple(sorted(shared_boundaries))
    boundary_indexes = {value: index for index, value in enumerate(boundaries)}
    if len(boundaries) >= 2:
        for left, right in zip(boundaries, boundaries[1:]):
            ET.SubElement(
                grid,
                _qn(W_NS, "gridCol"),
                {_qn(W_NS, "w"): str(max(right - left, 0))},
            )

    for row in table.rows:
        properties = row.properties
        row_boundaries = properties.cell_boundaries_twips
        grid_before = (
            boundary_indexes.get(row_boundaries[0], 0)
            if row_boundaries and boundaries
            else 0
        )
        grid_after = (
            len(boundaries) - 1 - boundary_indexes.get(row_boundaries[-1], 0)
            if row_boundaries and boundaries
            else 0
        )
        row_attributes = {}
        if properties.revision_save_id is not None:
            row_attributes[_qn(W_NS, "rsidTr")] = (
                f"{properties.revision_save_id:08X}"
            )
        row_element = ET.SubElement(
            table_element,
            _qn(W_NS, "tr"),
            row_attributes,
        )
        if (
            properties.height_twips is not None
            or properties.cant_split
            or properties.is_header
            or properties.cell_spacing_twips is not None
            or grid_before
            or grid_after
            or properties.grid_before_width_type is not None
            or properties.grid_after_width_type is not None
        ):
            row_properties = ET.SubElement(row_element, _qn(W_NS, "trPr"))
            if grid_before:
                ET.SubElement(
                    row_properties,
                    _qn(W_NS, "gridBefore"),
                    {_qn(W_NS, "val"): str(grid_before)},
                )
            if properties.grid_before_width_type is not None:
                ET.SubElement(
                    row_properties,
                    _qn(W_NS, "wBefore"),
                    {
                        _qn(W_NS, "w"): str(properties.grid_before_width or 0),
                        _qn(W_NS, "type"): properties.grid_before_width_type,
                    },
                )
            if grid_after:
                ET.SubElement(
                    row_properties,
                    _qn(W_NS, "gridAfter"),
                    {_qn(W_NS, "val"): str(grid_after)},
                )
            if properties.grid_after_width_type is not None:
                ET.SubElement(
                    row_properties,
                    _qn(W_NS, "wAfter"),
                    {
                        _qn(W_NS, "w"): str(properties.grid_after_width or 0),
                        _qn(W_NS, "type"): properties.grid_after_width_type,
                    },
                )
            if properties.cant_split:
                ET.SubElement(row_properties, _qn(W_NS, "cantSplit"))
            if properties.height_twips is not None:
                attributes = {_qn(W_NS, "val"): str(properties.height_twips)}
                if properties.height_rule is not None:
                    attributes[_qn(W_NS, "hRule")] = properties.height_rule
                ET.SubElement(row_properties, _qn(W_NS, "trHeight"), attributes)
            if properties.is_header:
                ET.SubElement(row_properties, _qn(W_NS, "tblHeader"))
            if properties.cell_spacing_twips is not None:
                ET.SubElement(
                    row_properties,
                    _qn(W_NS, "tblCellSpacing"),
                    {
                        _qn(W_NS, "w"): str(properties.cell_spacing_twips),
                        _qn(W_NS, "type"): "dxa",
                    },
                )
        row_boundary_index = 0
        for cell in row.cells:
            output_cell = cell
            if (
                row_boundaries
                and row_boundary_index + cell.grid_span < len(row_boundaries)
            ):
                left = row_boundaries[row_boundary_index]
                right = row_boundaries[row_boundary_index + cell.grid_span]
                inferred_span = boundary_indexes.get(right, 0) - boundary_indexes.get(
                    left,
                    0,
                )
                if inferred_span > 0 and inferred_span != cell.grid_span:
                    output_cell = replace(cell, grid_span=inferred_span)
                row_boundary_index += cell.grid_span
            _append_table_cell(
                row_element,
                output_cell,
                valid_paragraph_style_ids=valid_paragraph_style_ids,
                valid_character_style_ids=valid_character_style_ids,
                valid_table_style_ids=valid_table_style_ids or set(),
            )


def _document_xml(
    document: Document,
    header_footer_parts: tuple[_HeaderFooterPart, ...],
) -> bytes:
    valid_paragraph_style_ids = {
        style.index
        for style in document.styles.styles
        if style is not None and style.kind == "paragraph"
    }
    valid_character_style_ids = {
        style.index
        for style in document.styles.styles
        if style is not None and style.kind == "character"
    }
    valid_table_style_ids = {
        style.index
        for style in document.styles.styles
        if style is not None and style.kind == "table"
    }
    root = ET.Element(_qn(W_NS, "document"))
    body = ET.SubElement(root, _qn(W_NS, "body"))
    section_references: dict[
        tuple[int, int], tuple[_HeaderFooterPart, ...]
    ] = {}
    for section in document.sections:
        section_key = (section.cp_start, section.cp_end)
        section_references[section_key] = tuple(
            part for part in header_footer_parts if part.section_key == section_key
        )
    for block in document.body_blocks:
        if isinstance(block, Paragraph):
            _append_paragraph(
                body,
                block,
                valid_paragraph_style_ids=valid_paragraph_style_ids,
                valid_character_style_ids=valid_character_style_ids,
                section_references=section_references,
            )
        elif isinstance(block, Table):
            _append_table(
                body,
                block,
                valid_paragraph_style_ids=valid_paragraph_style_ids,
                valid_character_style_ids=valid_character_style_ids,
                valid_table_style_ids=valid_table_style_ids,
            )
    if document.sections:
        _append_section_properties(
            body,
            document.sections[-1],
            include_break_type=False,
            header_footer_parts=section_references.get(
                (
                    document.sections[-1].cp_start,
                    document.sections[-1].cp_end,
                ),
                (),
            ),
        )
    return _xml_bytes(root)


def _header_footer_xml(
    part: _HeaderFooterPart,
    document: Document,
) -> bytes:
    valid_paragraph_style_ids = {
        style.index
        for style in document.styles.styles
        if style is not None and style.kind == "paragraph"
    }
    valid_character_style_ids = {
        style.index
        for style in document.styles.styles
        if style is not None and style.kind == "character"
    }
    valid_table_style_ids = {
        style.index
        for style in document.styles.styles
        if style is not None and style.kind == "table"
    }
    root = ET.Element(_qn(W_NS, "hdr" if part.kind == "header" else "ftr"))
    blocks = part.story.body_blocks
    for block in blocks:
        if isinstance(block, Paragraph):
            _append_paragraph(
                root,
                block,
                valid_paragraph_style_ids=valid_paragraph_style_ids,
                valid_character_style_ids=valid_character_style_ids,
            )
        elif isinstance(block, Table):
            _append_table(
                root,
                block,
                valid_paragraph_style_ids=valid_paragraph_style_ids,
                valid_character_style_ids=valid_character_style_ids,
                valid_table_style_ids=valid_table_style_ids,
            )
    if not blocks:
        ET.SubElement(root, _qn(W_NS, "p"))
    return _xml_bytes(root)


def _note_marker_run(marker_name: str) -> ET.Element:
    run = ET.Element(_qn(W_NS, "r"))
    run_properties = ET.SubElement(run, _qn(W_NS, "rPr"))
    ET.SubElement(
        run_properties,
        _qn(W_NS, "vertAlign"),
        {_qn(W_NS, "val"): "superscript"},
    )
    ET.SubElement(run, _qn(W_NS, marker_name))
    return run


def _notes_xml(
    document: Document,
    values: tuple[Footnote, ...] | tuple[Endnote, ...],
    *,
    root_name: str,
    note_name: str,
    id_attribute: str,
    marker_name: str,
    separator_stories: tuple[
        tuple[int, str, str | None, NoteSeparatorStory | None], ...
    ],
) -> bytes:
    valid_paragraph_style_ids = {
        style.index
        for style in document.styles.styles
        if style is not None and style.kind == "paragraph"
    }
    valid_character_style_ids = {
        style.index
        for style in document.styles.styles
        if style is not None and style.kind == "character"
    }
    valid_table_style_ids = {
        style.index
        for style in document.styles.styles
        if style is not None and style.kind == "table"
    }
    root = ET.Element(_qn(W_NS, root_name))
    for note_id, note_type, default_mark_name, story in separator_stories:
        if story is None and default_mark_name is None:
            continue
        footnote = ET.SubElement(
            root,
            _qn(W_NS, note_name),
            {
                _qn(W_NS, "id"): str(note_id),
                _qn(W_NS, "type"): note_type,
            },
        )
        if story is None:
            paragraph = ET.SubElement(footnote, _qn(W_NS, "p"))
            run = ET.SubElement(paragraph, _qn(W_NS, "r"))
            assert default_mark_name is not None
            ET.SubElement(run, _qn(W_NS, default_mark_name))
            continue
        for block in story.body_blocks:
            if isinstance(block, Paragraph):
                _append_paragraph(
                    footnote,
                    block,
                    valid_paragraph_style_ids=valid_paragraph_style_ids,
                    valid_character_style_ids=valid_character_style_ids,
                )
            elif isinstance(block, Table):
                _append_table(
                    footnote,
                    block,
                    valid_paragraph_style_ids=valid_paragraph_style_ids,
                    valid_character_style_ids=valid_character_style_ids,
                    valid_table_style_ids=valid_table_style_ids,
                )
        if not story.body_blocks:
            ET.SubElement(footnote, _qn(W_NS, "p"))

    for value in values:
        footnote = ET.SubElement(
            root,
            _qn(W_NS, note_name),
            {_qn(W_NS, "id"): str(getattr(value, id_attribute))},
        )
        blocks = value.body_blocks
        marker_added = False
        for block in blocks:
            if isinstance(block, Paragraph):
                _append_paragraph(
                    footnote,
                    block,
                    valid_paragraph_style_ids=valid_paragraph_style_ids,
                    valid_character_style_ids=valid_character_style_ids,
                )
                if not marker_added:
                    paragraph = footnote[-1]
                    insert_at = (
                        1
                        if len(paragraph)
                        and paragraph[0].tag == _qn(W_NS, "pPr")
                        else 0
                    )
                    paragraph.insert(insert_at, _note_marker_run(marker_name))
                    marker_added = True
            elif isinstance(block, Table):
                if not marker_added:
                    paragraph = ET.SubElement(footnote, _qn(W_NS, "p"))
                    paragraph.append(_note_marker_run(marker_name))
                    marker_added = True
                _append_table(
                    footnote,
                    block,
                    valid_paragraph_style_ids=valid_paragraph_style_ids,
                    valid_character_style_ids=valid_character_style_ids,
                    valid_table_style_ids=valid_table_style_ids,
                )
        if not marker_added:
            paragraph = ET.SubElement(footnote, _qn(W_NS, "p"))
            paragraph.append(_note_marker_run(marker_name))
    return _xml_bytes(root)


def _footnotes_xml(document: Document) -> bytes:
    return _notes_xml(
        document,
        document.footnotes,
        root_name="footnotes",
        note_name="footnote",
        id_attribute="footnote_id",
        marker_name="footnoteRef",
        separator_stories=(
            (-1, "separator", "separator", document.footnote_separator),
            (
                0,
                "continuationSeparator",
                "continuationSeparator",
                document.footnote_continuation_separator,
            ),
            (
                -2,
                "continuationNotice",
                None,
                document.footnote_continuation_notice,
            ),
        ),
    )


def _endnotes_xml(document: Document) -> bytes:
    return _notes_xml(
        document,
        document.endnotes,
        root_name="endnotes",
        note_name="endnote",
        id_attribute="endnote_id",
        marker_name="endnoteRef",
        separator_stories=(
            (-1, "separator", "separator", document.endnote_separator),
            (
                0,
                "continuationSeparator",
                "continuationSeparator",
                document.endnote_continuation_separator,
            ),
            (
                -2,
                "continuationNotice",
                None,
                document.endnote_continuation_notice,
            ),
        ),
    )


def _comments_xml(document: Document) -> bytes:
    valid_paragraph_style_ids = {
        style.index
        for style in document.styles.styles
        if style is not None and style.kind == "paragraph"
    }
    valid_character_style_ids = {
        style.index
        for style in document.styles.styles
        if style is not None and style.kind == "character"
    }
    valid_table_style_ids = {
        style.index
        for style in document.styles.styles
        if style is not None and style.kind == "table"
    }
    root = ET.Element(_qn(W_NS, "comments"))
    for value in document.comments:
        comment = ET.SubElement(
            root,
            _qn(W_NS, "comment"),
            {
                _qn(W_NS, "id"): str(value.comment_id),
                _qn(W_NS, "author"): value.author,
                _qn(W_NS, "initials"): value.initials,
            },
        )
        for block in value.body_blocks:
            if isinstance(block, Paragraph):
                _append_paragraph(
                    comment,
                    block,
                    valid_paragraph_style_ids=valid_paragraph_style_ids,
                    valid_character_style_ids=valid_character_style_ids,
                )
            elif isinstance(block, Table):
                _append_table(
                    comment,
                    block,
                    valid_paragraph_style_ids=valid_paragraph_style_ids,
                    valid_character_style_ids=valid_character_style_ids,
                    valid_table_style_ids=valid_table_style_ids,
                )
        if not value.body_blocks:
            ET.SubElement(comment, _qn(W_NS, "p"))
    return _xml_bytes(root)


def _settings_xml(
    *,
    even_and_odd_headers: bool,
    mirror_margins: bool,
    gutter_at_top: bool,
    default_tab_stop_twips: int | None,
    auto_hyphenation: bool | None,
    do_not_hyphenate_caps: bool | None,
    hyphenation_zone_twips: int | None,
    consecutive_hyphen_limit: int | None,
    track_revisions: bool | None,
    document_protection_edit: str | None,
    adjust_line_height_in_table: bool | None,
) -> bytes:
    root = ET.Element(_qn(W_NS, "settings"))
    if mirror_margins:
        ET.SubElement(root, _qn(W_NS, "mirrorMargins"))
    if gutter_at_top:
        ET.SubElement(root, _qn(W_NS, "gutterAtTop"))
    _append_boolean_property(root, "trackRevisions", track_revisions)
    if document_protection_edit is not None:
        ET.SubElement(
            root,
            _qn(W_NS, "documentProtection"),
            {
                _qn(W_NS, "edit"): document_protection_edit,
                _qn(W_NS, "enforcement"): "1",
            },
        )
    if default_tab_stop_twips is not None:
        ET.SubElement(
            root,
            _qn(W_NS, "defaultTabStop"),
            {_qn(W_NS, "val"): str(default_tab_stop_twips)},
        )
    _append_boolean_property(root, "autoHyphenation", auto_hyphenation)
    if consecutive_hyphen_limit is not None:
        ET.SubElement(
            root,
            _qn(W_NS, "consecutiveHyphenLimit"),
            {_qn(W_NS, "val"): str(consecutive_hyphen_limit)},
        )
    if hyphenation_zone_twips is not None:
        ET.SubElement(
            root,
            _qn(W_NS, "hyphenationZone"),
            {_qn(W_NS, "val"): str(hyphenation_zone_twips)},
        )
    _append_boolean_property(
        root,
        "doNotHyphenateCaps",
        do_not_hyphenate_caps,
    )
    if even_and_odd_headers:
        ET.SubElement(root, _qn(W_NS, "evenAndOddHeaders"))
    if adjust_line_height_in_table:
        compatibility = ET.SubElement(root, _qn(W_NS, "compat"))
        ET.SubElement(
            compatibility,
            _qn(W_NS, "adjustLineHeightInTable"),
        )
    return _xml_bytes(root)


def _font_table_xml(fonts: tuple[FontDefinition, ...]) -> bytes:
    root = ET.Element(_qn(W_NS, "fonts"))
    for font in fonts:
        element = ET.SubElement(
            root,
            _qn(W_NS, "font"),
            {_qn(W_NS, "name"): font.name},
        )
        if font.alternate_name:
            ET.SubElement(
                element,
                _qn(W_NS, "altName"),
                {_qn(W_NS, "val"): font.alternate_name},
            )
        ET.SubElement(
            element,
            _qn(W_NS, "charset"),
            {_qn(W_NS, "val"): f"{font.charset:02X}"},
        )
        if font.family:
            ET.SubElement(
                element,
                _qn(W_NS, "family"),
                {_qn(W_NS, "val"): font.family},
            )
        if font.pitch:
            ET.SubElement(
                element,
                _qn(W_NS, "pitch"),
                {_qn(W_NS, "val"): font.pitch},
            )
        if len(font.panose) == 10 and any(font.panose):
            ET.SubElement(
                element,
                _qn(W_NS, "panose1"),
                {_qn(W_NS, "val"): font.panose.hex().upper()},
            )
        if len(font.signature) == 24 and any(font.signature):
            values = struct.unpack("<6I", font.signature)
            ET.SubElement(
                element,
                _qn(W_NS, "sig"),
                {
                    _qn(W_NS, "usb0"): f"{values[0]:08X}",
                    _qn(W_NS, "usb1"): f"{values[1]:08X}",
                    _qn(W_NS, "usb2"): f"{values[2]:08X}",
                    _qn(W_NS, "usb3"): f"{values[3]:08X}",
                    _qn(W_NS, "csb0"): f"{values[4]:08X}",
                    _qn(W_NS, "csb1"): f"{values[5]:08X}",
                },
            )
    return _xml_bytes(root)


def _styles_xml(style_sheet: StyleSheet) -> bytes:
    root = ET.Element(_qn(W_NS, "styles"))
    if _has_character_properties(style_sheet.default_character_properties):
        defaults = ET.SubElement(root, _qn(W_NS, "docDefaults"))
        run_default = ET.SubElement(defaults, _qn(W_NS, "rPrDefault"))
        run_properties = ET.SubElement(run_default, _qn(W_NS, "rPr"))
        _append_character_property_elements(
            run_properties,
            style_sheet.default_character_properties,
        )

    emitted_ids = {
        style.index
        for style in style_sheet.styles
        if style is not None and style.kind in ("paragraph", "character")
    }
    emitted_by_id = {
        style.index: style
        for style in style_sheet.styles
        if style is not None
        and style.kind in ("paragraph", "character", "table", "numbering")
    }
    for style in style_sheet.styles:
        if style is None or style.kind not in (
            "paragraph",
            "character",
            "table",
            "numbering",
        ):
            continue
        attributes = {
            _qn(W_NS, "type"): style.kind,
            _qn(W_NS, "styleId"): style.ooxml_style_id,
        }
        if style.kind == "paragraph" and style.index == 0:
            attributes[_qn(W_NS, "default")] = "1"
        element = ET.SubElement(root, _qn(W_NS, "style"), attributes)
        ET.SubElement(
            element,
            _qn(W_NS, "name"),
            {_qn(W_NS, "val"): style.name},
        )
        parent = emitted_by_id.get(style.based_on)
        same_kind_parent = parent is not None and parent.kind == style.kind
        if same_kind_parent:
            ET.SubElement(
                element,
                _qn(W_NS, "basedOn"),
                {_qn(W_NS, "val"): f"DocStyle{style.based_on}"},
            )
        next_style = emitted_by_id.get(style.next_style)
        if style.kind == "paragraph" and (
            next_style is not None and next_style.kind == "paragraph"
        ):
            ET.SubElement(
                element,
                _qn(W_NS, "next"),
                {_qn(W_NS, "val"): f"DocStyle{style.next_style}"},
            )
        paragraph_holder = ET.Element("holder")
        _append_paragraph_properties(
            paragraph_holder,
            style.paragraph_properties,
            valid_style_ids=emitted_ids,
        )
        paragraph_properties = paragraph_holder.find(_qn(W_NS, "pPr"))
        if paragraph_properties is not None:
            element.append(paragraph_properties)
        character_properties = style.character_properties
        if style.based_on is None and style.kind in ("paragraph", "character"):
            # DOC's Stshi defaults sit below every style in the inheritance
            # chain. WordprocessingML has no implicit access to that binary
            # layer, so root styles need their effective properties
            # materialized (notably the default Latin/East Asian fonts).
            character_properties = style_sheet.effective_character_at(
                style.index
            )
        elif parent is not None and not same_kind_parent:
            # WordprocessingML ignores basedOn across style types. DOC files
            # can base a character style on Normal, so materialize the resolved
            # character properties in that case instead of emitting an invalid
            # cross-type reference.
            character_properties = style_sheet.effective_character_at(style.index)
        if _has_character_properties(character_properties):
            run_properties = ET.SubElement(element, _qn(W_NS, "rPr"))
            _append_character_property_elements(
                run_properties,
                character_properties,
                valid_style_ids=emitted_ids,
            )
        if (
            style.kind == "table"
            and style.paragraph_properties.table_row is not None
        ):
            table_properties = ET.SubElement(element, _qn(W_NS, "tblPr"))
            _append_table_property_elements(
                table_properties,
                style.paragraph_properties.table_row,
                include_width=False,
            )
            _append_table_style_cell_properties(
                element,
                style.paragraph_properties.table_row,
            )
        for conditional in style.conditional_table_properties:
            conditional_element = ET.SubElement(
                element,
                _qn(W_NS, "tblStylePr"),
                {_qn(W_NS, "type"): conditional.condition},
            )
            conditional_paragraph_holder = ET.Element("holder")
            _append_paragraph_properties(
                conditional_paragraph_holder,
                conditional.paragraph_properties,
                valid_style_ids=emitted_ids,
            )
            conditional_paragraph = conditional_paragraph_holder.find(
                _qn(W_NS, "pPr")
            )
            if conditional_paragraph is not None:
                conditional_element.append(conditional_paragraph)
            if _has_character_properties(conditional.character_properties):
                conditional_run = ET.SubElement(
                    conditional_element,
                    _qn(W_NS, "rPr"),
                )
                _append_character_property_elements(
                    conditional_run,
                    conditional.character_properties,
                    valid_style_ids=emitted_ids,
                )
            if conditional.table_properties is not None:
                conditional_table = ET.Element(_qn(W_NS, "tblPr"))
                _append_table_property_elements(
                    conditional_table,
                    conditional.table_properties,
                    include_width=False,
                )
                if len(conditional_table):
                    conditional_element.append(conditional_table)
                _append_table_style_cell_properties(
                    conditional_element,
                    conditional.table_properties,
                )
    return _xml_bytes(root)


def _append_numbering_level(
    parent: ET.Element,
    level: NumberingLevel,
    *,
    valid_paragraph_style_ids: set[int],
) -> None:
    if not 0 <= level.level <= 8:
        raise PackageWriteError(f"numbering level {level.level} is outside 0..8")
    attributes = {_qn(W_NS, "ilvl"): str(level.level)}
    if level.tentative:
        attributes[_qn(W_NS, "tentative")] = "1"
    element = ET.SubElement(parent, _qn(W_NS, "lvl"), attributes)
    ET.SubElement(
        element,
        _qn(W_NS, "start"),
        {_qn(W_NS, "val"): str(level.start)},
    )
    ET.SubElement(
        element,
        _qn(W_NS, "numFmt"),
        {_qn(W_NS, "val"): level.number_format},
    )
    if level.restart_after_level is not None:
        ET.SubElement(
            element,
            _qn(W_NS, "lvlRestart"),
            {_qn(W_NS, "val"): str(level.restart_after_level)},
        )
    if (
        level.linked_style_id is not None
        and level.linked_style_id in valid_paragraph_style_ids
    ):
        ET.SubElement(
            element,
            _qn(W_NS, "pStyle"),
            {_qn(W_NS, "val"): f"DocStyle{level.linked_style_id}"},
        )
    if level.legal:
        ET.SubElement(element, _qn(W_NS, "isLgl"))
    ET.SubElement(
        element,
        _qn(W_NS, "suff"),
        {_qn(W_NS, "val"): level.suffix},
    )
    ET.SubElement(
        element,
        _qn(W_NS, "lvlText"),
        {_qn(W_NS, "val"): level.text},
    )
    ET.SubElement(
        element,
        _qn(W_NS, "lvlJc"),
        {_qn(W_NS, "val"): level.justification},
    )
    paragraph_holder = ET.Element("holder")
    _append_paragraph_properties(
        paragraph_holder,
        level.paragraph_properties,
        valid_style_ids=valid_paragraph_style_ids,
    )
    paragraph_properties = paragraph_holder.find(_qn(W_NS, "pPr"))
    if paragraph_properties is not None:
        element.append(paragraph_properties)
    if _has_character_properties(level.character_properties):
        character_properties = ET.SubElement(element, _qn(W_NS, "rPr"))
        _append_character_property_elements(
            character_properties,
            level.character_properties,
        )


def _numbering_xml(
    numbering: NumberingDefinitions,
    style_sheet: StyleSheet,
) -> bytes:
    root = ET.Element(_qn(W_NS, "numbering"))
    abstract_ids = [value.abstract_id for value in numbering.abstracts]
    if any(value < 0 for value in abstract_ids) or len(set(abstract_ids)) != len(
        abstract_ids
    ):
        raise PackageWriteError(
            "abstract numbering identifiers must be unique and nonnegative"
        )
    instance_ids = [value.numbering_id for value in numbering.instances]
    if any(value <= 0 for value in instance_ids) or len(set(instance_ids)) != len(
        instance_ids
    ):
        raise PackageWriteError(
            "numbering instance identifiers must be unique and positive"
        )
    valid_paragraph_style_ids = {
        style.index
        for style in style_sheet.styles
        if style is not None and style.kind == "paragraph"
    }
    valid_abstract_ids = set(abstract_ids)
    for abstract in numbering.abstracts:
        levels = [value.level for value in abstract.levels]
        if not levels or len(set(levels)) != len(levels):
            raise PackageWriteError(
                f"abstract numbering {abstract.abstract_id} has invalid levels"
            )
        element = ET.SubElement(
            root,
            _qn(W_NS, "abstractNum"),
            {_qn(W_NS, "abstractNumId"): str(abstract.abstract_id)},
        )
        ET.SubElement(
            element,
            _qn(W_NS, "multiLevelType"),
            {_qn(W_NS, "val"): abstract.kind},
        )
        if abstract.name:
            ET.SubElement(
                element,
                _qn(W_NS, "name"),
                {_qn(W_NS, "val"): abstract.name},
            )
        for level in abstract.levels:
            _append_numbering_level(
                element,
                level,
                valid_paragraph_style_ids=valid_paragraph_style_ids,
            )
    for instance in numbering.instances:
        if instance.abstract_id not in valid_abstract_ids:
            raise PackageWriteError(
                f"numbering instance {instance.numbering_id} references an absent "
                f"abstract numbering definition {instance.abstract_id}"
            )
        element = ET.SubElement(
            root,
            _qn(W_NS, "num"),
            {_qn(W_NS, "numId"): str(instance.numbering_id)},
        )
        ET.SubElement(
            element,
            _qn(W_NS, "abstractNumId"),
            {_qn(W_NS, "val"): str(instance.abstract_id)},
        )
        override_levels: set[int] = set()
        for override in instance.overrides:
            if not 0 <= override.level <= 8 or override.level in override_levels:
                raise PackageWriteError(
                    f"numbering instance {instance.numbering_id} has invalid overrides"
                )
            override_levels.add(override.level)
            override_element = ET.SubElement(
                element,
                _qn(W_NS, "lvlOverride"),
                {_qn(W_NS, "ilvl"): str(override.level)},
            )
            if override.start is not None:
                ET.SubElement(
                    override_element,
                    _qn(W_NS, "startOverride"),
                    {_qn(W_NS, "val"): str(override.start)},
                )
            if override.replacement is not None:
                _append_numbering_level(
                    override_element,
                    override.replacement,
                    valid_paragraph_style_ids=valid_paragraph_style_ids,
                )
    return _xml_bytes(root)


def _core_properties_xml(properties: CoreProperties) -> bytes:
    root = ET.Element(_qn(CP_NS, "coreProperties"))
    simple_values = (
        (DC_NS, "title", properties.title),
        (DC_NS, "subject", properties.subject),
        (DC_NS, "creator", properties.creator),
        (CP_NS, "keywords", properties.keywords),
        (DC_NS, "description", properties.description),
        (CP_NS, "lastModifiedBy", properties.last_modified_by),
        (CP_NS, "revision", properties.revision),
    )
    for namespace, name, value in simple_values:
        if value is not None:
            ET.SubElement(root, _qn(namespace, name)).text = value
    date_values = (
        ("created", properties.created),
        ("modified", properties.modified),
    )
    for name, value in date_values:
        if value is None:
            continue
        element = ET.SubElement(root, _qn(DCTERMS_NS, name))
        element.set(_qn(XSI_NS, "type"), "dcterms:W3CDTF")
        element.text = value
    if properties.last_printed is not None:
        ET.SubElement(root, _qn(CP_NS, "lastPrinted")).text = (
            properties.last_printed
        )
    return _xml_bytes(root)


def _write_part(package: zipfile.ZipFile, name: str, data: bytes) -> None:
    info = zipfile.ZipInfo(name, date_time=(1980, 1, 1, 0, 0, 0))
    info.compress_type = zipfile.ZIP_DEFLATED
    info.external_attr = 0o644 << 16
    package.writestr(info, data)


def write_docx(document: Document, destination: str | Path) -> None:
    output = Path(destination)
    has_styles = any(
        style is not None and style.kind in ("paragraph", "character", "table")
        for style in document.styles.styles
    )
    has_fonts = bool(document.fonts)
    has_settings = (
        document.even_and_odd_headers
        or document.mirror_margins
        or document.gutter_at_top
        or document.default_tab_stop_twips is not None
        or document.auto_hyphenation is not None
        or document.do_not_hyphenate_caps is not None
        or document.hyphenation_zone_twips is not None
        or document.consecutive_hyphen_limit is not None
        or document.track_revisions is not None
        or document.document_protection_edit is not None
        or document.adjust_line_height_in_table is True
    )
    has_footnotes = bool(
        document.footnotes
        or document.footnote_separator
        or document.footnote_continuation_separator
        or document.footnote_continuation_notice
    )
    has_endnotes = bool(
        document.endnotes
        or document.endnote_separator
        or document.endnote_continuation_separator
        or document.endnote_continuation_notice
    )
    has_comments = bool(document.comments)
    has_numbering = bool(
        document.numbering.abstracts or document.numbering.instances
    )
    has_core_properties = document.core_properties.has_values
    picture_ids = [picture.picture_id for picture in document.pictures]
    if any(picture_id <= 0 for picture_id in picture_ids) or len(
        set(picture_ids)
    ) != len(picture_ids):
        raise PackageWriteError("inline picture identifiers must be unique and positive")
    object_ids = [value.object_id for value in document.embedded_objects]
    if any(object_id <= 0 for object_id in object_ids) or len(
        set(object_ids)
    ) != len(object_ids):
        raise PackageWriteError(
            "embedded object identifiers must be unique and positive"
        )
    header_footer_parts = _build_header_footer_parts(
        document,
        has_styles=has_styles,
        has_fonts=has_fonts,
        has_settings=has_settings,
        has_footnotes=has_footnotes,
        has_endnotes=has_endnotes,
        has_comments=has_comments,
        has_numbering=has_numbering,
    )
    main_pictures = _pictures_in_blocks(document.body_blocks)
    footnote_pictures = _pictures_in_note_part(
        document.footnotes,
        (
            document.footnote_separator,
            document.footnote_continuation_separator,
            document.footnote_continuation_notice,
        ),
    )
    endnote_pictures = _pictures_in_note_part(
        document.endnotes,
        (
            document.endnote_separator,
            document.endnote_continuation_separator,
            document.endnote_continuation_notice,
        ),
    )
    try:
        with zipfile.ZipFile(output, mode="w") as package:
            _write_part(
                package,
                "[Content_Types].xml",
                _content_types_xml(
                    has_styles=has_styles,
                    has_fonts=has_fonts,
                    has_settings=has_settings,
                    has_footnotes=has_footnotes,
                    has_endnotes=has_endnotes,
                    has_comments=has_comments,
                    has_numbering=has_numbering,
                    has_core_properties=has_core_properties,
                    pictures=document.pictures,
                    embedded_objects=document.embedded_objects,
                    header_footer_parts=header_footer_parts,
                ),
            )
            _write_part(
                package,
                "_rels/.rels",
                _root_relationships_xml(
                    has_core_properties=has_core_properties,
                ),
            )
            if has_core_properties:
                _write_part(
                    package,
                    "docProps/core.xml",
                    _core_properties_xml(document.core_properties),
                )
            _write_part(
                package,
                "word/document.xml",
                _document_xml(document, header_footer_parts),
            )
            if (
                has_styles
                or has_fonts
                or has_settings
                or has_footnotes
                or has_endnotes
                or has_comments
                or has_numbering
                or main_pictures
                or document.embedded_objects
                or header_footer_parts
            ):
                _write_part(
                    package,
                    "word/_rels/document.xml.rels",
                    _document_relationships_xml(
                        has_styles=has_styles,
                        has_fonts=has_fonts,
                        has_settings=has_settings,
                        has_footnotes=has_footnotes,
                        has_endnotes=has_endnotes,
                        has_comments=has_comments,
                        has_numbering=has_numbering,
                        pictures=main_pictures,
                        embedded_objects=document.embedded_objects,
                        header_footer_parts=header_footer_parts,
                    ),
                )
            if has_styles:
                _write_part(package, "word/styles.xml", _styles_xml(document.styles))
            if has_fonts:
                _write_part(
                    package,
                    "word/fontTable.xml",
                    _font_table_xml(document.fonts),
                )
            if has_settings:
                _write_part(
                    package,
                    "word/settings.xml",
                    _settings_xml(
                        even_and_odd_headers=document.even_and_odd_headers,
                        mirror_margins=document.mirror_margins,
                        gutter_at_top=document.gutter_at_top,
                        default_tab_stop_twips=(
                            document.default_tab_stop_twips
                        ),
                        auto_hyphenation=document.auto_hyphenation,
                        do_not_hyphenate_caps=(
                            document.do_not_hyphenate_caps
                        ),
                        hyphenation_zone_twips=(
                            document.hyphenation_zone_twips
                        ),
                        consecutive_hyphen_limit=(
                            document.consecutive_hyphen_limit
                        ),
                        track_revisions=document.track_revisions,
                        document_protection_edit=(
                            document.document_protection_edit
                        ),
                        adjust_line_height_in_table=(
                            document.adjust_line_height_in_table
                        ),
                    ),
                )
            if has_footnotes:
                _write_part(
                    package,
                    "word/footnotes.xml",
                    _footnotes_xml(document),
                )
                if footnote_pictures:
                    _write_part(
                        package,
                        "word/_rels/footnotes.xml.rels",
                        _image_relationships_xml(footnote_pictures),
                    )
            if has_endnotes:
                _write_part(
                    package,
                    "word/endnotes.xml",
                    _endnotes_xml(document),
                )
                if endnote_pictures:
                    _write_part(
                        package,
                        "word/_rels/endnotes.xml.rels",
                        _image_relationships_xml(endnote_pictures),
                    )
            if has_comments:
                _write_part(
                    package,
                    "word/comments.xml",
                    _comments_xml(document),
                )
            if has_numbering:
                _write_part(
                    package,
                    "word/numbering.xml",
                    _numbering_xml(document.numbering, document.styles),
                )
            for picture in document.pictures:
                _write_part(
                    package,
                    f"word/media/image{picture.picture_id}.{picture.extension}",
                    picture.data,
                )
            for embedded_object in document.embedded_objects:
                _write_part(
                    package,
                    (
                        "word/embeddings/"
                        f"oleObject{embedded_object.object_id}.bin"
                    ),
                    embedded_object.data,
                )
            for part in header_footer_parts:
                _write_part(
                    package,
                    f"word/{part.part_name}",
                    _header_footer_xml(part, document),
                )
                part_pictures = _pictures_in_blocks(part.story.body_blocks)
                if part_pictures:
                    _write_part(
                        package,
                        f"word/_rels/{part.part_name}.rels",
                        _image_relationships_xml(part_pictures),
                    )
    except (OSError, ValueError, zipfile.BadZipFile) as exc:
        raise PackageWriteError(f"could not write DOCX package: {exc}") from exc


def validate_docx(path: str | Path) -> None:
    required_parts = {
        "[Content_Types].xml",
        "_rels/.rels",
        "word/document.xml",
    }
    try:
        with zipfile.ZipFile(path) as package:
            names = set(package.namelist())
            missing = required_parts - names
            if missing:
                raise PackageWriteError(
                    f"generated DOCX is missing parts: {', '.join(sorted(missing))}"
                )
            corrupt_part = package.testzip()
            if corrupt_part is not None:
                raise PackageWriteError(
                    f"generated DOCX contains corrupt ZIP part {corrupt_part!r}"
                )
            for name in names:
                if name.endswith(".xml") or name.endswith(".rels"):
                    ET.fromstring(package.read(name))
    except PackageWriteError:
        raise
    except (OSError, ET.ParseError, zipfile.BadZipFile) as exc:
        raise PackageWriteError(f"generated DOCX failed validation: {exc}") from exc
