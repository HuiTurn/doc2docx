"""End-to-end conversion and inspection APIs."""

from __future__ import annotations

from collections.abc import Iterable, Iterator
from dataclasses import dataclass
import os
from pathlib import Path
import stat
import tempfile
from typing import Any

from .cfb import CompoundFile, CompoundFileLimits, ObjectType
from .diagnostics import ConversionReport
from .errors import (
    EncryptedDocumentError,
    InvalidWordDocument,
    StreamNotFound,
    UnsafeOutputPathError,
)
from .model import (
    CoreProperties,
    Document,
    Paragraph,
    Symbol,
    Table,
    parse_main_story,
)
from .oleps import read_summary_information
from .msdoc import (
    FileInformationBlock,
    read_bookmarks,
    read_comments,
    read_document_settings,
    read_endnotes,
    read_field_table,
    read_font_table,
    read_formatting,
    read_footnotes,
    read_header_floating_pictures,
    read_header_footer_stories,
    read_header_textboxes,
    read_main_floating_pictures,
    read_main_textboxes,
    read_numbering,
    read_officeart_shapes,
    read_inline_pictures,
    read_piece_table,
    read_sections,
    read_shape_anchors,
    read_style_sheet,
)
from .ooxml import validate_docx, write_docx


@dataclass(slots=True, frozen=True)
class ConversionResult:
    output_path: Path
    report: ConversionReport
    document: Document


def _iter_tables(blocks: Iterable[Paragraph | Table]) -> Iterator[Table]:
    for block in blocks:
        if not isinstance(block, Table):
            continue
        yield block
        for row in block.rows:
            for cell in row.cells:
                yield from _iter_tables(cell.body_blocks)


def _load_word_parts(
    source: str | Path,
    *,
    limits: CompoundFileLimits | None,
) -> tuple[CompoundFile, bytes, FileInformationBlock]:
    compound = CompoundFile.from_path(source, limits=limits)
    word_document = compound.open_stream("WordDocument")
    fib = FileInformationBlock.parse(word_document)
    return compound, word_document, fib


def convert(
    source: str | Path,
    destination: str | Path | None = None,
    *,
    limits: CompoundFileLimits | None = None,
) -> ConversionResult:
    source_path = Path(source)
    destination_path = (
        Path(destination) if destination is not None else source_path.with_suffix(".docx")
    )
    if destination_path.suffix.lower() != ".docx":
        raise UnsafeOutputPathError("destination must use the .docx extension")
    if source_path.resolve() == destination_path.resolve():
        raise UnsafeOutputPathError("destination must not overwrite the source document")
    report = ConversionReport(str(source_path), str(destination_path))

    compound, word_document, fib = _load_word_parts(source_path, limits=limits)
    try:
        summary_information = read_summary_information(
            compound.open_stream("\x05SummaryInformation"),
            report=report,
        )
    except StreamNotFound:
        summary_information = CoreProperties()
    except InvalidWordDocument as exc:
        summary_information = CoreProperties()
        report.warning(
            "SUMMARY_INFORMATION_MALFORMED",
            "malformed optional document metadata was omitted",
            reason=str(exc),
        )
    repaired_entries = [entry for entry in compound.entries if entry.name_was_repaired]
    if repaired_entries:
        report.warning(
            "CFB_DIRECTORY_REPAIRED",
            "a malformed root directory name was safely normalized",
            entry_count=len(repaired_entries),
        )
    if fib.base.is_encrypted:
        method = "XOR obfuscation" if fib.base.is_obfuscated else "RC4 encryption"
        raise EncryptedDocumentError(
            f"password-protected Word documents using {method} are not yet supported"
        )

    table_name = fib.base.table_stream_name
    table_stream = compound.open_stream(table_name)
    try:
        data_stream = compound.open_stream("Data")
    except StreamNotFound:
        data_stream = None
    dop = fib.dop
    document_settings = read_document_settings(
        table_stream,
        offset=dop.fc,
        size=dop.lcb,
        n_fib=fib.n_fib,
    )
    section_table = fib.plcf_sed
    sections = read_sections(
        table_stream,
        word_document,
        offset=section_table.fc,
        size=section_table.lcb,
        main_story_cp_count=fib.ccp_text,
        document_lid=fib.base.lid,
        report=report,
        default_footnote_position=document_settings.footnote_position,
        default_footnote_number_format=(
            document_settings.footnote_number_format
        ),
        default_footnote_number_start=document_settings.footnote_number_start,
        default_footnote_number_restart=(
            document_settings.footnote_number_restart
        ),
        default_endnote_position=document_settings.endnote_position,
        default_endnote_number_format=document_settings.endnote_number_format,
        default_endnote_number_start=document_settings.endnote_number_start,
        default_endnote_number_restart=document_settings.endnote_number_restart,
    )
    font_table = fib.sttbf_ffn
    fonts = read_font_table(
        table_stream,
        offset=font_table.fc,
        size=font_table.lcb,
        report=report,
    )
    style_table = fib.stshf
    style_sheet = read_style_sheet(
        table_stream,
        offset=style_table.fc,
        size=style_table.lcb,
        fonts=fonts,
        report=report,
    )
    available_style_names = frozenset(
        style.name for style in style_sheet.styles if style is not None
    )
    list_table = fib.plf_lst
    list_override_table = fib.plf_lfo
    list_name_table = fib.sttb_list_names
    numbering = read_numbering(
        table_stream,
        list_offset=list_table.fc,
        list_size=list_table.lcb,
        lfo_offset=list_override_table.fc,
        lfo_size=list_override_table.lcb,
        ccp_text=fib.ccp_text,
        fonts=fonts,
        report=report,
        list_names_offset=list_name_table.fc,
        list_names_size=list_name_table.lcb,
    )
    available_list_names = frozenset(
        abstract.name
        for abstract in numbering.abstracts
        if abstract.name is not None
    )
    clx = fib.clx
    piece_table = read_piece_table(
        table_stream,
        word_document,
        fc_clx=clx.fc,
        lcb_clx=clx.lcb,
        report=report,
    )
    if fib.ccp_text > piece_table.cp_end:
        raise InvalidWordDocument(
            f"FIB main-story length {fib.ccp_text} exceeds Piece Table range "
            f"{piece_table.cp_end}"
        )
    if fib.total_story_cp_count > piece_table.cp_end:
        raise InvalidWordDocument(
            f"FIB document-story length {fib.total_story_cp_count} exceeds "
            f"Piece Table range {piece_table.cp_end}"
        )
    chpx = fib.plcf_bte_chpx
    papx = fib.plcf_bte_papx
    formatting = read_formatting(
        table_stream,
        word_document,
        piece_table,
        fc_plcf_bte_chpx=chpx.fc,
        lcb_plcf_bte_chpx=chpx.lcb,
        fc_plcf_bte_papx=papx.fc,
        lcb_plcf_bte_papx=papx.lcb,
        report=report,
        fonts=fonts,
        style_sheet=style_sheet,
        data_stream=data_stream,
    )
    bookmark_names = fib.sttbf_bkmk
    bookmark_starts = fib.plcf_bkf
    bookmark_ends = fib.plcf_bkl
    bookmarks = read_bookmarks(
        table_stream,
        names_offset=bookmark_names.fc,
        names_size=bookmark_names.lcb,
        starts_offset=bookmark_starts.fc,
        starts_size=bookmark_starts.lcb,
        ends_offset=bookmark_ends.fc,
        ends_size=bookmark_ends.lcb,
        main_story_length=fib.ccp_text,
        total_story_length=fib.total_story_cp_count,
        report=report,
    )
    main_field_table = fib.plcf_fld_mom
    main_fields = read_field_table(
        table_stream,
        piece_table,
        offset=main_field_table.fc,
        size=main_field_table.lcb,
        story_length=fib.ccp_text,
        story_cp_start=0,
        structure="PlcfFldMom",
        story_name="main",
        report=report,
        character_properties_at=formatting.character_properties_at,
    )
    footnote_field_table = fib.plcf_fld_ftn
    footnote_fields = read_field_table(
        table_stream,
        piece_table,
        offset=footnote_field_table.fc,
        size=footnote_field_table.lcb,
        story_length=fib.ccp_footnotes,
        story_cp_start=fib.ccp_text,
        structure="PlcfFldFtn",
        story_name="footnotes",
        report=report,
        character_properties_at=formatting.character_properties_at,
    )
    header_field_table = fib.plcf_fld_hdr
    header_fields = read_field_table(
        table_stream,
        piece_table,
        offset=header_field_table.fc,
        size=header_field_table.lcb,
        story_length=fib.ccp_headers,
        story_cp_start=fib.header_story_cp_start,
        structure="PlcfFldHdr",
        story_name="headers",
        report=report,
        character_properties_at=formatting.character_properties_at,
    )
    comment_field_table = fib.plcf_fld_atn
    comment_fields = read_field_table(
        table_stream,
        piece_table,
        offset=comment_field_table.fc,
        size=comment_field_table.lcb,
        story_length=fib.ccp_comments,
        story_cp_start=fib.comment_story_cp_start,
        structure="PlcfFldAtn",
        story_name="comments",
        report=report,
        character_properties_at=formatting.character_properties_at,
    )
    endnote_field_table = fib.plcf_fld_edn
    endnote_fields = read_field_table(
        table_stream,
        piece_table,
        offset=endnote_field_table.fc,
        size=endnote_field_table.lcb,
        story_length=fib.ccp_endnotes,
        story_cp_start=fib.endnote_story_cp_start,
        structure="PlcfFldEdn",
        story_name="endnotes",
        report=report,
        character_properties_at=formatting.character_properties_at,
    )
    footnote_reference_table = fib.plcf_fnd_ref
    footnote_text_table = fib.plcf_fnd_txt
    footnotes = read_footnotes(
        table_stream,
        piece_table,
        ccp_text=fib.ccp_text,
        ccp_footnotes=fib.ccp_footnotes,
        reference_offset=footnote_reference_table.fc,
        reference_size=footnote_reference_table.lcb,
        text_offset=footnote_text_table.fc,
        text_size=footnote_text_table.lcb,
        report=report,
        character_properties_at=formatting.character_properties_at,
        paragraph_properties_at=formatting.paragraph_properties_at,
        field_end_properties_at=footnote_fields.end_properties_at,
        bookmark_names=bookmarks.names,
        style_names=available_style_names,
        list_names=available_list_names,
    )
    comment_reference_table = fib.plcf_and_ref
    comment_text_table = fib.plcf_and_txt
    comment_owners = fib.grp_xst_atn_owners
    comment_bookmark_tags = fib.sttbf_atn_bkmk
    comment_bookmark_starts = fib.plcf_atn_bkf
    comment_bookmark_ends = fib.plcf_atn_bkl
    comments = read_comments(
        table_stream,
        piece_table,
        ccp_text=fib.ccp_text,
        ccp_comments=fib.ccp_comments,
        comment_story_cp_start=fib.comment_story_cp_start,
        reference_offset=comment_reference_table.fc,
        reference_size=comment_reference_table.lcb,
        text_offset=comment_text_table.fc,
        text_size=comment_text_table.lcb,
        owners_offset=comment_owners.fc,
        owners_size=comment_owners.lcb,
        bookmark_tags_offset=comment_bookmark_tags.fc,
        bookmark_tags_size=comment_bookmark_tags.lcb,
        bookmark_starts_offset=comment_bookmark_starts.fc,
        bookmark_starts_size=comment_bookmark_starts.lcb,
        bookmark_ends_offset=comment_bookmark_ends.fc,
        bookmark_ends_size=comment_bookmark_ends.lcb,
        report=report,
        character_properties_at=formatting.character_properties_at,
        paragraph_properties_at=formatting.paragraph_properties_at,
        field_end_properties_at=comment_fields.end_properties_at,
        bookmark_names=bookmarks.names,
        style_names=available_style_names,
        list_names=available_list_names,
    )
    endnote_reference_table = fib.plcf_end_ref
    endnote_text_table = fib.plcf_end_txt
    endnotes = read_endnotes(
        table_stream,
        piece_table,
        ccp_text=fib.ccp_text,
        ccp_endnotes=fib.ccp_endnotes,
        endnote_story_cp_start=fib.endnote_story_cp_start,
        reference_offset=endnote_reference_table.fc,
        reference_size=endnote_reference_table.lcb,
        text_offset=endnote_text_table.fc,
        text_size=endnote_text_table.lcb,
        report=report,
        character_properties_at=formatting.character_properties_at,
        paragraph_properties_at=formatting.paragraph_properties_at,
        field_end_properties_at=endnote_fields.end_properties_at,
        bookmark_names=bookmarks.names,
        style_names=available_style_names,
        list_names=available_list_names,
    )
    spa_headers = fib.plc_spa_hdr
    dgg_info = fib.dgg_info
    officeart_shapes = read_officeart_shapes(
        table_stream,
        offset=dgg_info.fc,
        size=dgg_info.lcb,
        delay_stream=word_document,
    )
    main_shape_table = fib.plc_spa_mom
    main_shape_anchors = read_shape_anchors(
        table_stream,
        piece_table,
        offset=main_shape_table.fc,
        size=main_shape_table.lcb,
        ccp_anchor_story=fib.ccp_text,
        anchor_story_cp_start=0,
        spa_structure="PlcSpaMom",
        anchor_story_name="main",
        report=report,
    )
    main_textbox_table = fib.plcf_txbx_txt
    main_textbox_fields = fib.plcf_fld_txbx
    main_textbox_breaks = fib.plcf_txbx_bkd
    main_textboxes = read_main_textboxes(
        table_stream,
        piece_table,
        ccp_text=fib.ccp_text,
        ccp_textboxes=fib.ccp_textboxes,
        textbox_cp_start=fib.textbox_story_cp_start,
        spa_offset=main_shape_table.fc,
        spa_size=main_shape_table.lcb,
        text_offset=main_textbox_table.fc,
        text_size=main_textbox_table.lcb,
        field_offset=main_textbox_fields.fc,
        field_size=main_textbox_fields.lcb,
        break_offset=main_textbox_breaks.fc,
        break_size=main_textbox_breaks.lcb,
        report=report,
        character_properties_at=formatting.character_properties_at,
        paragraph_properties_at=formatting.paragraph_properties_at,
        shape_style_at=officeart_shapes.style_at,
        bookmark_names=bookmarks.names,
        style_names=available_style_names,
        list_names=available_list_names,
    )
    header_textbox_table = fib.plcf_hdr_txbx_txt
    header_textbox_fields = fib.plcf_fld_hdr_txbx
    header_textbox_breaks = fib.plcf_txbx_hdr_bkd
    header_textboxes = read_header_textboxes(
        table_stream,
        piece_table,
        ccp_headers=fib.ccp_headers,
        header_story_cp_start=fib.header_story_cp_start,
        ccp_header_textboxes=fib.ccp_header_textboxes,
        header_textbox_cp_start=fib.header_textbox_story_cp_start,
        spa_offset=spa_headers.fc,
        spa_size=spa_headers.lcb,
        text_offset=header_textbox_table.fc,
        text_size=header_textbox_table.lcb,
        field_offset=header_textbox_fields.fc,
        field_size=header_textbox_fields.lcb,
        break_offset=header_textbox_breaks.fc,
        break_size=header_textbox_breaks.lcb,
        report=report,
        character_properties_at=formatting.character_properties_at,
        paragraph_properties_at=formatting.paragraph_properties_at,
        shape_style_at=officeart_shapes.style_at,
        bookmark_names=bookmarks.names,
        style_names=available_style_names,
        list_names=available_list_names,
    )
    main_characters = piece_table.extract_characters(
        0,
        fib.ccp_text,
        report,
        story="main",
    )
    header_characters = piece_table.extract_characters(
        fib.header_story_cp_start,
        fib.header_story_cp_start + fib.ccp_headers,
        report,
        story="headers",
    )
    inline_pictures = read_inline_pictures(
        data_stream,
        main_characters,
        report=report,
        character_properties_at=formatting.character_properties_at,
    )
    floating_pictures = read_main_floating_pictures(
        main_shape_anchors,
        officeart_shapes,
        excluded_shape_ids=main_textboxes.shape_ids,
        first_picture_id=len(inline_pictures.pictures) + 1,
        report=report,
        character_properties_at=formatting.character_properties_at,
    )
    header_inline_pictures = read_inline_pictures(
        data_stream,
        header_characters,
        first_picture_id=(
            len(inline_pictures.pictures) + len(floating_pictures.pictures) + 1
        ),
        story_name="headers",
        report=report,
        character_properties_at=formatting.character_properties_at,
    )
    header_shape_anchors = read_shape_anchors(
        table_stream,
        piece_table,
        offset=spa_headers.fc,
        size=spa_headers.lcb,
        ccp_anchor_story=fib.ccp_headers,
        anchor_story_cp_start=fib.header_story_cp_start,
        spa_structure="PlcSpaHdr",
        anchor_story_name="headers",
        report=report,
    )
    header_floating_pictures = read_header_floating_pictures(
        header_shape_anchors,
        officeart_shapes,
        header_story_cp_start=fib.header_story_cp_start,
        excluded_shape_ids=header_textboxes.shape_ids,
        first_picture_id=(
            len(inline_pictures.pictures)
            + len(floating_pictures.pictures)
            + len(header_inline_pictures.pictures)
            + 1
        ),
        report=report,
        character_properties_at=formatting.character_properties_at,
    )
    header_table = fib.plcf_hdd
    header_footers = read_header_footer_stories(
        table_stream,
        piece_table,
        sections,
        offset=header_table.fc,
        size=header_table.lcb,
        ccp_headers=fib.ccp_headers,
        header_story_cp_start=fib.header_story_cp_start,
        report=report,
        character_properties_at=formatting.character_properties_at,
        paragraph_properties_at=formatting.paragraph_properties_at,
        floating_textbox_at=header_textboxes.textbox_at,
        inline_picture_at=header_inline_pictures.picture_at,
        floating_picture_at=header_floating_pictures.picture_at,
        field_end_properties_at=header_fields.end_properties_at,
        bookmark_names=bookmarks.names,
        style_names=available_style_names,
        list_names=available_list_names,
        ignored_character_cps=(
            header_inline_pictures.consumed_binary_data_cps
        ),
    )
    sections = header_footers.sections
    parsed_document = parse_main_story(
        main_characters,
        report,
        character_properties_at=formatting.character_properties_at,
        paragraph_properties_at=formatting.paragraph_properties_at,
        floating_textbox_at=main_textboxes.textbox_at,
        inline_picture_at=inline_pictures.picture_at,
        floating_picture_at=floating_pictures.picture_at,
        footnote_reference_at=footnotes.reference_at,
        endnote_reference_at=endnotes.reference_at,
        comment_reference_at=comments.reference_at,
        comment_boundaries_at=comments.boundaries_at,
        field_end_properties_at=main_fields.end_properties_at,
        bookmark_boundaries_at=bookmarks.boundaries_at,
        bookmark_names=bookmarks.names,
        style_names=available_style_names,
        list_names=available_list_names,
        ignored_character_cps=inline_pictures.consumed_binary_data_cps,
        sections=sections,
    )
    document = Document(
        paragraphs=parsed_document.paragraphs,
        fonts=fonts,
        styles=style_sheet,
        blocks=parsed_document.blocks,
        sections=sections,
        footnotes=footnotes.footnotes,
        endnotes=endnotes.endnotes,
        footnote_separator=header_footers.footnote_separator,
        footnote_continuation_separator=(
            header_footers.footnote_continuation_separator
        ),
        footnote_continuation_notice=(
            header_footers.footnote_continuation_notice
        ),
        endnote_separator=header_footers.endnote_separator,
        endnote_continuation_separator=(
            header_footers.endnote_continuation_separator
        ),
        endnote_continuation_notice=(
            header_footers.endnote_continuation_notice
        ),
        comments=comments.comments,
        core_properties=summary_information,
        numbering=numbering,
        pictures=(
            inline_pictures.pictures
            + floating_pictures.pictures
            + header_inline_pictures.pictures
            + header_floating_pictures.pictures
        ),
        even_and_odd_headers=document_settings.even_and_odd_headers,
        adjust_line_height_in_table=(
            document_settings.adjust_line_height_in_table
        ),
    )
    tables = tuple(_iter_tables(document.body_blocks))

    report.statistics.update(
        {
            "cfb_sector_count": compound.sector_count,
            "table_stream": table_name,
            "fib_version": fib.n_fib,
            "piece_count": len(piece_table.pieces),
            "main_story_cp_count": fib.ccp_text,
            "paragraph_count": len(document.paragraphs),
            "character_format_span_count": len(formatting.character_spans),
            "paragraph_format_span_count": len(formatting.paragraph_spans),
            "character_fkp_run_count": formatting.character_fkp_run_count,
            "paragraph_fkp_run_count": formatting.paragraph_fkp_run_count,
            "font_count": len(fonts),
            "style_count": sum(
                1 for style in style_sheet.styles if style is not None
            ),
            "core_property_count": summary_information.value_count,
            "declared_field_count": sum(
                field_table.field_count
                for field_table in (
                    main_fields,
                    footnote_fields,
                    header_fields,
                    comment_fields,
                    endnote_fields,
                )
            )
            + main_textboxes.field_count
            + header_textboxes.field_count,
            "declared_field_character_count": sum(
                field_table.character_count
                for field_table in (
                    main_fields,
                    footnote_fields,
                    header_fields,
                    comment_fields,
                    endnote_fields,
                )
            )
            + main_textboxes.field_character_count
            + header_textboxes.field_character_count,
            "bookmark_count": bookmarks.bookmark_count,
            "preserved_bookmark_count": bookmarks.preserved_count,
            "column_bookmark_count": bookmarks.column_bookmark_count,
            "abstract_numbering_count": len(numbering.abstracts),
            "named_list_count": len(available_list_names),
            "numbering_instance_count": len(numbering.instances),
            "numbering_level_count": sum(
                len(abstract.levels) for abstract in numbering.abstracts
            ),
            "numbered_paragraph_count": sum(
                paragraph.properties.numbering_id is not None
                and paragraph.properties.numbering_suppressed is not True
                and paragraph.properties.numbering_skipped is not True
                for paragraph in document.paragraphs
            ),
            "table_style_count": sum(
                1
                for style in style_sheet.styles
                if style is not None and style.kind == "table"
            ),
            "numbering_style_count": sum(
                1
                for style in style_sheet.styles
                if style is not None and style.kind == "numbering"
            ),
            "piece_prm_count": sum(
                1 for piece in piece_table.pieces if piece.prm
            ),
            "clx_prc_count": len(piece_table.prcs),
            "table_count": len(tables),
            "styled_table_count": sum(
                bool(table.rows)
                and table.rows[0].properties.table_style_id is not None
                for table in tables
            ),
            "preferred_width_table_count": sum(
                bool(table.rows)
                and table.rows[0].properties.preferred_width_type is not None
                for table in tables
            ),
            "cell_width_override_count": sum(
                len(row.properties.cell_width_overrides)
                for table in tables
                for row in table.rows
            ),
            "table_row_count": sum(len(table.rows) for table in tables),
            "table_cell_count": sum(
                len(row.cells) for table in tables for row in table.rows
            ),
            "section_count": len(sections),
            "document_grid_section_count": sum(
                section.document_grid_type is not None for section in sections
            ),
            "section_page_number_format_count": sum(
                section.page_number_format is not None for section in sections
            ),
            "section_page_number_start_count": sum(
                section.page_number_start is not None for section in sections
            ),
            "chapter_numbered_section_count": sum(
                section.page_number_chapter_style is not None
                for section in sections
            ),
            "page_bordered_section_count": sum(
                section.page_borders is not None for section in sections
            ),
            "line_numbered_section_count": sum(
                section.line_number_count_by is not None for section in sections
            ),
            "column_separator_section_count": sum(
                section.column_separator is True for section in sections
            ),
            "unequal_column_section_count": sum(
                section.column_widths_twips is not None for section in sections
            ),
            "vertically_aligned_section_count": sum(
                section.vertical_alignment not in (None, "top")
                for section in sections
            ),
            "section_note_numbering_override_count": sum(
                any(
                    value is not None
                    for value in (
                        section.footnote_number_format,
                        section.footnote_number_start,
                        section.footnote_number_restart,
                        section.endnote_number_format,
                        section.endnote_number_start,
                        section.endnote_number_restart,
                    )
                )
                for section in sections
            ),
            "section_note_number_start_count": sum(
                section.footnote_number_start is not None
                or section.endnote_number_start is not None
                for section in sections
            ),
            "section_note_placement_count": sum(
                section.footnote_position is not None
                or section.endnote_position is not None
                or section.suppress_endnotes is True
                for section in sections
            ),
            "bidirectional_section_count": sum(
                section.bidirectional is True for section in sections
            ),
            "vertical_text_section_count": sum(
                section.text_direction not in (None, "lrTb")
                for section in sections
            ),
            "adjust_line_height_in_table": (
                document.adjust_line_height_in_table is True
            ),
            "header_footer_story_count": header_footers.story_count,
            "header_footer_paragraph_count": header_footers.paragraph_count,
            "note_separator_story_count": (
                header_footers.note_separator_story_count
            ),
            "header_textbox_count": header_textboxes.textbox_count,
            "header_textbox_field_count": header_textboxes.field_count,
            "styled_header_textbox_count": (
                header_textboxes.styled_textbox_count
            ),
            "main_textbox_count": main_textboxes.textbox_count,
            "main_textbox_field_count": main_textboxes.field_count,
            "styled_main_textbox_count": main_textboxes.styled_textbox_count,
            "footnote_count": len(footnotes.footnotes),
            "footnote_reference_count": footnotes.reference_count,
            "custom_footnote_mark_count": footnotes.custom_mark_count,
            "endnote_count": len(endnotes.endnotes),
            "endnote_reference_count": endnotes.reference_count,
            "custom_endnote_mark_count": endnotes.custom_mark_count,
            "comment_count": len(comments.comments),
            "comment_reference_count": comments.reference_count,
            "comment_range_count": comments.range_count,
            "inline_picture_count": (
                len(inline_pictures.pictures)
                + len(header_inline_pictures.pictures)
            ),
            "main_inline_picture_count": len(inline_pictures.pictures),
            "header_inline_picture_count": len(header_inline_pictures.pictures),
            "deferred_inline_picture_count": (
                inline_pictures.deferred_count
                + header_inline_pictures.deferred_count
            ),
            "deferred_header_inline_picture_count": (
                header_inline_pictures.deferred_count
            ),
            "inline_binary_data_count": (
                inline_pictures.binary_data_count
                + header_inline_pictures.binary_data_count
            ),
            "consumed_binary_field_data_count": (
                len(inline_pictures.consumed_binary_data_cps)
                + len(header_inline_pictures.consumed_binary_data_cps)
            ),
            "floating_picture_count": (
                len(floating_pictures.pictures)
                + len(header_floating_pictures.pictures)
            ),
            "main_floating_picture_count": len(floating_pictures.pictures),
            "header_floating_picture_count": len(
                header_floating_pictures.pictures
            ),
            "deferred_floating_picture_count": (
                floating_pictures.deferred_count
                + header_floating_pictures.deferred_count
            ),
            "deferred_header_floating_picture_count": (
                header_floating_pictures.deferred_count
            ),
            "non_picture_floating_shape_count": (
                floating_pictures.non_picture_shape_count
                + header_floating_pictures.non_picture_shape_count
            ),
            "symbol_character_count": sum(
                isinstance(inline, Symbol)
                for paragraph in document.paragraphs
                for inline in paragraph.inlines
            ),
            "custom_tab_stop_count": sum(
                len(paragraph.properties.tab_stops or ())
                for paragraph in document.paragraphs
            )
            + sum(
                len(style.paragraph_properties.tab_stops or ())
                for style in style_sheet.styles
                if style is not None
            ),
        }
    )
    if (
        fib.base.has_pictures
        and not inline_pictures.pictures
        and not header_inline_pictures.pictures
        and not floating_pictures.pictures
        and not header_floating_pictures.pictures
    ):
        report.warning(
            "PICTURES_DEFERRED",
            "the FIB reports pictures, but no supported picture was recovered",
        )
    secondary_stories = fib.secondary_story_character_counts
    secondary_stories.pop("footnotes", None)
    secondary_stories.pop("endnotes", None)
    secondary_stories.pop("comments", None)
    secondary_stories.pop("textboxes", None)
    secondary_stories.pop("headers", None)
    secondary_stories.pop("header_textboxes", None)
    if secondary_stories:
        report.warning(
            "SECONDARY_STORIES_DEFERRED",
            "some secondary document stories remain unsupported after M7d",
            stories=secondary_stories,
        )

    destination_path.parent.mkdir(parents=True, exist_ok=True)
    destination_mode = (
        stat.S_IMODE(destination_path.stat().st_mode)
        if destination_path.exists()
        else 0o644
    )
    temporary_path: Path | None = None
    try:
        with tempfile.NamedTemporaryFile(
            prefix=f".{destination_path.name}.",
            suffix=".tmp",
            dir=destination_path.parent,
            delete=False,
        ) as temporary:
            temporary_path = Path(temporary.name)
        write_docx(document, temporary_path)
        validate_docx(temporary_path)
        os.chmod(temporary_path, destination_mode)
        os.replace(temporary_path, destination_path)
        temporary_path = None
    finally:
        if temporary_path is not None:
            try:
                temporary_path.unlink()
            except FileNotFoundError:
                pass

    report.info("CONVERSION_COMPLETE", "conversion completed")
    return ConversionResult(destination_path, report, document)


def inspect_doc(
    source: str | Path,
    *,
    limits: CompoundFileLimits | None = None,
) -> dict[str, Any]:
    compound, _, fib = _load_word_parts(source, limits=limits)
    entries = []
    for entry in compound.entries:
        if entry.path == "":
            continue
        entries.append(
            {
                "path": entry.path,
                "type": entry.object_type.name.lower(),
                "size": entry.stream_size
                if entry.object_type is ObjectType.STREAM
                else None,
                "starting_sector": entry.starting_sector,
            }
        )
    return {
        "path": str(Path(source)),
        "cfb": {
            "major_version": compound.header.major_version,
            "minor_version": compound.header.minor_version,
            "sector_size": compound.header.sector_size,
            "mini_sector_size": compound.header.mini_sector_size,
            "sector_count": compound.sector_count,
            "directory_repairs": sum(
                1 for entry in compound.entries if entry.name_was_repaired
            ),
        },
        "fib": {
            "nFib": fib.n_fib,
            "lid": fib.base.lid,
            "encrypted": fib.base.is_encrypted,
            "obfuscated": fib.base.is_obfuscated,
            "table_stream": fib.base.table_stream_name,
            "ccpText": fib.ccp_text,
            "ccpFtn": fib.ccp_footnotes,
            "ccpEdn": fib.ccp_endnotes,
            "ccpAtn": fib.ccp_comments,
            "ccpHdd": fib.ccp_headers,
            "ccpHdrTxbx": fib.ccp_header_textboxes,
            "ccpTxbx": fib.ccp_textboxes,
            "fcClx": fib.clx.fc,
            "lcbClx": fib.clx.lcb,
            "fcPlcffndRef": fib.plcf_fnd_ref.fc,
            "lcbPlcffndRef": fib.plcf_fnd_ref.lcb,
            "fcPlcffndTxt": fib.plcf_fnd_txt.fc,
            "lcbPlcffndTxt": fib.plcf_fnd_txt.lcb,
            "fcPlcfandRef": fib.plcf_and_ref.fc,
            "lcbPlcfandRef": fib.plcf_and_ref.lcb,
            "fcPlcfandTxt": fib.plcf_and_txt.fc,
            "lcbPlcfandTxt": fib.plcf_and_txt.lcb,
            "fcGrpXstAtnOwners": fib.grp_xst_atn_owners.fc,
            "lcbGrpXstAtnOwners": fib.grp_xst_atn_owners.lcb,
            "fcSttbfAtnBkmk": fib.sttbf_atn_bkmk.fc,
            "lcbSttbfAtnBkmk": fib.sttbf_atn_bkmk.lcb,
            "fcPlcfAtnBkf": fib.plcf_atn_bkf.fc,
            "lcbPlcfAtnBkf": fib.plcf_atn_bkf.lcb,
            "fcPlcfAtnBkl": fib.plcf_atn_bkl.fc,
            "lcbPlcfAtnBkl": fib.plcf_atn_bkl.lcb,
            "fcPlcfendRef": fib.plcf_end_ref.fc,
            "lcbPlcfendRef": fib.plcf_end_ref.lcb,
            "fcPlcfendTxt": fib.plcf_end_txt.fc,
            "lcbPlcfendTxt": fib.plcf_end_txt.lcb,
            "fcPlcfBteChpx": fib.plcf_bte_chpx.fc,
            "lcbPlcfBteChpx": fib.plcf_bte_chpx.lcb,
            "fcPlcfBtePapx": fib.plcf_bte_papx.fc,
            "lcbPlcfBtePapx": fib.plcf_bte_papx.lcb,
            "fcStshf": fib.stshf.fc,
            "lcbStshf": fib.stshf.lcb,
            "fcPlcfSed": fib.plcf_sed.fc,
            "lcbPlcfSed": fib.plcf_sed.lcb,
            "fcPlcfHdd": fib.plcf_hdd.fc,
            "lcbPlcfHdd": fib.plcf_hdd.lcb,
            "fcPlcSpaHdr": fib.plc_spa_hdr.fc,
            "lcbPlcSpaHdr": fib.plc_spa_hdr.lcb,
            "fcPlcSpaMom": fib.plc_spa_mom.fc,
            "lcbPlcSpaMom": fib.plc_spa_mom.lcb,
            "fcDggInfo": fib.dgg_info.fc,
            "lcbDggInfo": fib.dgg_info.lcb,
            "fcPlcfHdrtxbxTxt": fib.plcf_hdr_txbx_txt.fc,
            "lcbPlcfHdrtxbxTxt": fib.plcf_hdr_txbx_txt.lcb,
            "fcPlcftxbxTxt": fib.plcf_txbx_txt.fc,
            "lcbPlcftxbxTxt": fib.plcf_txbx_txt.lcb,
            "fcPlcffldTxbx": fib.plcf_fld_txbx.fc,
            "lcbPlcffldTxbx": fib.plcf_fld_txbx.lcb,
            "fcPlcffldHdrTxbx": fib.plcf_fld_hdr_txbx.fc,
            "lcbPlcffldHdrTxbx": fib.plcf_fld_hdr_txbx.lcb,
            "fcPlcfTxbxHdrBkd": fib.plcf_txbx_hdr_bkd.fc,
            "lcbPlcfTxbxHdrBkd": fib.plcf_txbx_hdr_bkd.lcb,
            "fcPlcfTxbxBkd": fib.plcf_txbx_bkd.fc,
            "lcbPlcfTxbxBkd": fib.plcf_txbx_bkd.lcb,
            "fcDop": fib.dop.fc,
            "lcbDop": fib.dop.lcb,
            "fcSttbfFfn": fib.sttbf_ffn.fc,
            "lcbSttbfFfn": fib.sttbf_ffn.lcb,
            "fcPlcfFldMom": fib.plcf_fld_mom.fc,
            "lcbPlcfFldMom": fib.plcf_fld_mom.lcb,
            "fcPlcfFldHdr": fib.plcf_fld_hdr.fc,
            "lcbPlcfFldHdr": fib.plcf_fld_hdr.lcb,
            "fcPlcfFldFtn": fib.plcf_fld_ftn.fc,
            "lcbPlcfFldFtn": fib.plcf_fld_ftn.lcb,
            "fcPlcfFldAtn": fib.plcf_fld_atn.fc,
            "lcbPlcfFldAtn": fib.plcf_fld_atn.lcb,
            "fcPlcfFldEdn": fib.plcf_fld_edn.fc,
            "lcbPlcfFldEdn": fib.plcf_fld_edn.lcb,
            "fcSttbfBkmk": fib.sttbf_bkmk.fc,
            "lcbSttbfBkmk": fib.sttbf_bkmk.lcb,
            "fcPlcfBkf": fib.plcf_bkf.fc,
            "lcbPlcfBkf": fib.plcf_bkf.lcb,
            "fcPlcfBkl": fib.plcf_bkl.fc,
            "lcbPlcfBkl": fib.plcf_bkl.lcb,
            "fcPlfLst": fib.plf_lst.fc,
            "lcbPlfLst": fib.plf_lst.lcb,
            "fcPlfLfo": fib.plf_lfo.fc,
            "lcbPlfLfo": fib.plf_lfo.lcb,
            "fcSttbListNames": fib.sttb_list_names.fc,
            "lcbSttbListNames": fib.sttb_list_names.lcb,
        },
        "entries": sorted(entries, key=lambda item: item["path"]),
    }
