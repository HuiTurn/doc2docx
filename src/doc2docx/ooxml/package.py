"""Minimal deterministic OPC/WordprocessingML package writer."""

from __future__ import annotations

from pathlib import Path
import zipfile
from xml.etree import ElementTree as ET

from ..errors import PackageWriteError
from ..model import (
    Break,
    BreakType,
    CharacterProperties,
    Document,
    ParagraphProperties,
    Tab,
    TextRun,
)


W_NS = "http://schemas.openxmlformats.org/wordprocessingml/2006/main"
REL_NS = "http://schemas.openxmlformats.org/package/2006/relationships"
CONTENT_TYPES_NS = "http://schemas.openxmlformats.org/package/2006/content-types"
OFFICE_DOCUMENT_REL = (
    "http://schemas.openxmlformats.org/officeDocument/2006/relationships/officeDocument"
)
WORD_DOCUMENT_CONTENT_TYPE = (
    "application/vnd.openxmlformats-officedocument.wordprocessingml.document.main+xml"
)
XML_NS = "http://www.w3.org/XML/1998/namespace"

ET.register_namespace("w", W_NS)


def _qn(namespace: str, local_name: str) -> str:
    return f"{{{namespace}}}{local_name}"


def _xml_bytes(root: ET.Element) -> bytes:
    return ET.tostring(root, encoding="utf-8", xml_declaration=True)


def _content_types_xml() -> bytes:
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


def _append_run_properties(
    run: ET.Element,
    properties: CharacterProperties,
) -> None:
    if properties == CharacterProperties():
        return
    run_properties = ET.SubElement(run, _qn(W_NS, "rPr"))
    _append_boolean_property(run_properties, "b", properties.bold)
    _append_boolean_property(run_properties, "i", properties.italic)
    _append_boolean_property(run_properties, "caps", properties.caps)
    _append_boolean_property(run_properties, "smallCaps", properties.small_caps)
    _append_boolean_property(run_properties, "strike", properties.strike)
    _append_boolean_property(run_properties, "dstrike", properties.double_strike)
    _append_boolean_property(run_properties, "vanish", properties.hidden)
    if properties.color is not None:
        ET.SubElement(
            run_properties,
            _qn(W_NS, "color"),
            {_qn(W_NS, "val"): properties.color},
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
        ET.SubElement(run_properties, _qn(W_NS, "szCs"), attributes)
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


def _append_paragraph_properties(
    paragraph: ET.Element,
    properties: ParagraphProperties,
) -> None:
    # style_id is intentionally not serialized until the DOC style hierarchy
    # and a corresponding DOCX styles part are available.
    serializable = (
        properties.justification is not None
        or properties.keep_lines is not None
        or properties.keep_next is not None
        or properties.page_break_before is not None
        or properties.left_indent_twips is not None
        or properties.right_indent_twips is not None
        or properties.first_line_indent_twips is not None
        or properties.space_before_twips is not None
        or properties.space_after_twips is not None
        or properties.line_spacing_twips is not None
    )
    if not serializable:
        return
    paragraph_properties = ET.SubElement(paragraph, _qn(W_NS, "pPr"))
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
    spacing: dict[str, str] = {}
    if properties.space_before_twips is not None:
        spacing[_qn(W_NS, "before")] = str(properties.space_before_twips)
    if properties.space_after_twips is not None:
        spacing[_qn(W_NS, "after")] = str(properties.space_after_twips)
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


def _append_text_run(
    paragraph_element: ET.Element,
    text: str,
    properties: CharacterProperties,
) -> None:
    run = ET.SubElement(paragraph_element, _qn(W_NS, "r"))
    _append_run_properties(run, properties)
    text_element = ET.SubElement(run, _qn(W_NS, "t"))
    if text[:1].isspace() or text[-1:].isspace() or "  " in text:
        text_element.set(_qn(XML_NS, "space"), "preserve")
    text_element.text = text


def _document_xml(document: Document) -> bytes:
    root = ET.Element(_qn(W_NS, "document"))
    body = ET.SubElement(root, _qn(W_NS, "body"))
    for paragraph in document.paragraphs:
        paragraph_element = ET.SubElement(body, _qn(W_NS, "p"))
        _append_paragraph_properties(paragraph_element, paragraph.properties)
        for inline in paragraph.inlines:
            if isinstance(inline, TextRun):
                _append_text_run(
                    paragraph_element,
                    inline.text,
                    inline.properties,
                )
            elif isinstance(inline, Tab):
                run = ET.SubElement(paragraph_element, _qn(W_NS, "r"))
                _append_run_properties(run, inline.properties)
                ET.SubElement(run, _qn(W_NS, "tab"))
            elif isinstance(inline, Break):
                run = ET.SubElement(paragraph_element, _qn(W_NS, "r"))
                _append_run_properties(run, inline.properties)
                attributes = (
                    {_qn(W_NS, "type"): "page"}
                    if inline.kind is BreakType.PAGE
                    else {}
                )
                ET.SubElement(run, _qn(W_NS, "br"), attributes)
    return _xml_bytes(root)


def _write_part(package: zipfile.ZipFile, name: str, data: bytes) -> None:
    info = zipfile.ZipInfo(name, date_time=(1980, 1, 1, 0, 0, 0))
    info.compress_type = zipfile.ZIP_DEFLATED
    info.external_attr = 0o644 << 16
    package.writestr(info, data)


def write_docx(document: Document, destination: str | Path) -> None:
    output = Path(destination)
    try:
        with zipfile.ZipFile(output, mode="w") as package:
            _write_part(package, "[Content_Types].xml", _content_types_xml())
            _write_part(package, "_rels/.rels", _root_relationships_xml())
            _write_part(package, "word/document.xml", _document_xml(document))
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
            for name in required_parts:
                if name.endswith(".xml") or name.endswith(".rels"):
                    ET.fromstring(package.read(name))
    except PackageWriteError:
        raise
    except (OSError, ET.ParseError, zipfile.BadZipFile) as exc:
        raise PackageWriteError(f"generated DOCX failed validation: {exc}") from exc
