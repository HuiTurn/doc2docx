"""Minimal deterministic OPC/WordprocessingML package writer."""

from __future__ import annotations

from pathlib import Path
import zipfile
from xml.etree import ElementTree as ET

from ..errors import PackageWriteError
from ..model import Break, BreakType, Document, Tab, TextRun


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


def _append_text_run(paragraph_element: ET.Element, text: str) -> None:
    run = ET.SubElement(paragraph_element, _qn(W_NS, "r"))
    text_element = ET.SubElement(run, _qn(W_NS, "t"))
    if text[:1].isspace() or text[-1:].isspace() or "  " in text:
        text_element.set(_qn(XML_NS, "space"), "preserve")
    text_element.text = text


def _document_xml(document: Document) -> bytes:
    root = ET.Element(_qn(W_NS, "document"))
    body = ET.SubElement(root, _qn(W_NS, "body"))
    for paragraph in document.paragraphs:
        paragraph_element = ET.SubElement(body, _qn(W_NS, "p"))
        for inline in paragraph.inlines:
            if isinstance(inline, TextRun):
                _append_text_run(paragraph_element, inline.text)
            elif isinstance(inline, Tab):
                run = ET.SubElement(paragraph_element, _qn(W_NS, "r"))
                ET.SubElement(run, _qn(W_NS, "tab"))
            elif isinstance(inline, Break):
                run = ET.SubElement(paragraph_element, _qn(W_NS, "r"))
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
