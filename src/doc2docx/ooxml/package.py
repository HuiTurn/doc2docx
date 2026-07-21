"""Minimal deterministic OPC/WordprocessingML package writer."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
import struct
import zipfile
from xml.etree import ElementTree as ET

from ..errors import PackageWriteError
from ..model import (
    BorderProperties,
    Break,
    BreakType,
    CharacterProperties,
    Document,
    Field,
    FloatingTextBox,
    FontDefinition,
    HeaderFooterStory,
    Paragraph,
    ParagraphProperties,
    SectionProperties,
    ShadingProperties,
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
XML_NS = "http://www.w3.org/XML/1998/namespace"
VML_NS = "urn:schemas-microsoft-com:vml"
OFFICE_NS = "urn:schemas-microsoft-com:office:office"
WORD_2003_NS = "urn:schemas-microsoft-com:office:word"

ET.register_namespace("w", W_NS)
ET.register_namespace("r", R_NS)
ET.register_namespace("v", VML_NS)
ET.register_namespace("o", OFFICE_NS)
ET.register_namespace("w10", WORD_2003_NS)


@dataclass(slots=True, frozen=True)
class _HeaderFooterPart:
    section_key: tuple[int, int]
    kind: str
    reference_type: str
    part_name: str
    relationship_id: str
    story: HeaderFooterStory


def _qn(namespace: str, local_name: str) -> str:
    return f"{{{namespace}}}{local_name}"


def _xml_bytes(root: ET.Element) -> bytes:
    return ET.tostring(root, encoding="utf-8", xml_declaration=True)


def _content_types_xml(
    *,
    has_styles: bool,
    has_fonts: bool,
    has_settings: bool,
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
    ET.SubElement(
        root,
        "Override",
        PartName="/word/document.xml",
        ContentType=WORD_DOCUMENT_CONTENT_TYPE,
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


def _root_relationships_xml() -> bytes:
    root = ET.Element("Relationships", xmlns=REL_NS)
    ET.SubElement(
        root,
        "Relationship",
        Id="rId1",
        Type=OFFICE_DOCUMENT_REL,
        Target="word/document.xml",
    )
    return _xml_bytes(root)


def _document_relationships_xml(
    *,
    has_styles: bool,
    has_fonts: bool,
    has_settings: bool,
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
    for part in header_footer_parts:
        ET.SubElement(
            root,
            "Relationship",
            Id=part.relationship_id,
            Type=HEADER_REL if part.kind == "header" else FOOTER_REL,
            Target=part.part_name,
        )
    return _xml_bytes(root)


def _build_header_footer_parts(
    document: Document,
    *,
    has_styles: bool,
    has_fonts: bool,
    has_settings: bool,
) -> tuple[_HeaderFooterPart, ...]:
    relationship_number = 1 + sum((has_styles, has_fonts, has_settings))
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
    return properties != CharacterProperties()


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
    _append_boolean_property(run_properties, "noProof", properties.no_proof)
    _append_boolean_property(run_properties, "snapToGrid", properties.snap_to_grid)
    _append_boolean_property(run_properties, "vanish", properties.hidden)
    if properties.color is not None:
        ET.SubElement(
            run_properties,
            _qn(W_NS, "color"),
            {_qn(W_NS, "val"): properties.color},
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
        ET.SubElement(
            run_properties,
            _qn(W_NS, "u"),
            {_qn(W_NS, "val"): properties.underline},
        )
    if properties.vertical_align is not None:
        ET.SubElement(
            run_properties,
            _qn(W_NS, "vertAlign"),
            {_qn(W_NS, "val"): properties.vertical_align},
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


def _append_run_properties(
    run: ET.Element,
    properties: CharacterProperties,
    *,
    valid_style_ids: set[int] | None = None,
) -> None:
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
        or properties.kinsoku is not None
        or properties.word_wrap is not None
        or properties.overflow_punctuation is not None
        or properties.top_line_punctuation is not None
        or properties.auto_space_east_asian_latin is not None
        or properties.auto_space_east_asian_numbers is not None
        or properties.snap_to_grid is not None
        or properties.adjust_right_indent is not None
        or properties.borders is not None
        or properties.tab_stops is not None
        or properties.left_indent_twips is not None
        or properties.right_indent_twips is not None
        or properties.first_line_indent_twips is not None
        or properties.space_before_twips is not None
        or properties.space_after_twips is not None
        or properties.space_before_lines is not None
        or properties.space_after_lines is not None
        or properties.line_spacing_twips is not None
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
    _append_boolean_property(
        paragraph_properties,
        "widowControl",
        properties.widow_control,
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
        "adjustRightInd",
        properties.adjust_right_indent,
    )
    _append_boolean_property(
        paragraph_properties,
        "snapToGrid",
        properties.snap_to_grid,
    )
    if properties.borders is not None:
        _append_borders(
            paragraph_properties,
            "pBdr",
            properties.borders,
            include_inside=False,
        )
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
    if indentation:
        ET.SubElement(paragraph_properties, _qn(W_NS, "ind"), indentation)
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


def _twips_as_points(value: int) -> str:
    points = value / 20
    return f"{points:.2f}".rstrip("0").rstrip(".")


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
    ET.SubElement(
        begin_run,
        _qn(W_NS, "fldChar"),
        {_qn(W_NS, "fldCharType"): "begin"},
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
    style = ";".join(
        (
            "position:absolute",
            f"margin-left:{_twips_as_points(textbox.left_twips)}pt",
            f"margin-top:{_twips_as_points(textbox.top_twips)}pt",
            f"width:{_twips_as_points(textbox.width_twips)}pt",
            f"height:{_twips_as_points(textbox.height_twips)}pt",
            f"z-index:{-1 if textbox.behind_text else 1}",
            f"mso-position-horizontal-relative:{horizontal_relative}",
            f"mso-position-vertical-relative:{vertical_relative}",
        )
    )
    run = ET.SubElement(paragraph_element, _qn(W_NS, "r"))
    pict = ET.SubElement(run, _qn(W_NS, "pict"))
    shape = ET.SubElement(
        pict,
        _qn(VML_NS, "rect"),
        {
            "id": f"_x0000_s{textbox.shape_id}",
            "style": style,
            "stroked": "f",
            "filled": "f",
            _qn(OFFICE_NS, "allowincell"): "f",
        },
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
    vml_textbox = ET.SubElement(
        shape,
        _qn(VML_NS, "textbox"),
        {"inset": "0,0,0,0"},
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
    inline: TextRun | Symbol | Tab | Break | Field | FloatingTextBox,
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
    elif isinstance(inline, Tab):
        run = ET.SubElement(paragraph_element, _qn(W_NS, "r"))
        _append_run_properties(
            run,
            inline.properties,
            valid_style_ids=valid_character_style_ids,
        )
        ET.SubElement(run, _qn(W_NS, "tab"))
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
        ET.SubElement(run, _qn(W_NS, "br"), attributes)
    elif isinstance(inline, Field):
        _append_field(
            paragraph_element,
            inline,
            valid_paragraph_style_ids=valid_paragraph_style_ids,
            valid_character_style_ids=valid_character_style_ids,
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
    section_properties = ET.SubElement(parent, _qn(W_NS, "sectPr"))
    for part in header_footer_parts:
        ET.SubElement(
            section_properties,
            _qn(W_NS, f"{part.kind}Reference"),
            {
                _qn(W_NS, "type"): part.reference_type,
                _qn(R_NS, "id"): part.relationship_id,
            },
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
    if section.title_page:
        ET.SubElement(section_properties, _qn(W_NS, "titlePg"))
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
    paragraph_element = ET.SubElement(parent, _qn(W_NS, "p"))
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
    _append_cell_margins(
        parent,
        properties.default_cell_margins,
        container_name="tblCellMar",
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
        or cell.vertical_alignment is not None
        or cell.fit_text is not None
        or cell.no_wrap is not None
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
    boundaries = (
        first_properties.cell_boundaries_twips if first_properties is not None else ()
    )
    if len(boundaries) >= 2:
        for left, right in zip(boundaries, boundaries[1:]):
            ET.SubElement(
                grid,
                _qn(W_NS, "gridCol"),
                {_qn(W_NS, "w"): str(max(right - left, 0))},
            )

    for row in table.rows:
        row_element = ET.SubElement(table_element, _qn(W_NS, "tr"))
        properties = row.properties
        if (
            properties.height_twips is not None
            or properties.cant_split
            or properties.is_header
        ):
            row_properties = ET.SubElement(row_element, _qn(W_NS, "trPr"))
            if properties.cant_split:
                ET.SubElement(row_properties, _qn(W_NS, "cantSplit"))
            if properties.height_twips is not None:
                attributes = {_qn(W_NS, "val"): str(properties.height_twips)}
                if properties.height_rule is not None:
                    attributes[_qn(W_NS, "hRule")] = properties.height_rule
                ET.SubElement(row_properties, _qn(W_NS, "trHeight"), attributes)
            if properties.is_header:
                ET.SubElement(row_properties, _qn(W_NS, "tblHeader"))
        for cell in row.cells:
            _append_table_cell(
                row_element,
                cell,
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


def _settings_xml(
    *,
    even_and_odd_headers: bool,
    adjust_line_height_in_table: bool | None,
) -> bytes:
    root = ET.Element(_qn(W_NS, "settings"))
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
        if style is not None and style.kind in ("paragraph", "character", "table")
    }
    for style in style_sheet.styles:
        if style is None or style.kind not in ("paragraph", "character", "table"):
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
        or document.adjust_line_height_in_table is True
    )
    header_footer_parts = _build_header_footer_parts(
        document,
        has_styles=has_styles,
        has_fonts=has_fonts,
        has_settings=has_settings,
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
                    header_footer_parts=header_footer_parts,
                ),
            )
            _write_part(package, "_rels/.rels", _root_relationships_xml())
            _write_part(
                package,
                "word/document.xml",
                _document_xml(document, header_footer_parts),
            )
            if has_styles or has_fonts or has_settings or header_footer_parts:
                _write_part(
                    package,
                    "word/_rels/document.xml.rels",
                    _document_relationships_xml(
                        has_styles=has_styles,
                        has_fonts=has_fonts,
                        has_settings=has_settings,
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
                        adjust_line_height_in_table=(
                            document.adjust_line_height_in_table
                        ),
                    ),
                )
            for part in header_footer_parts:
                _write_part(
                    package,
                    f"word/{part.part_name}",
                    _header_footer_xml(part, document),
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
