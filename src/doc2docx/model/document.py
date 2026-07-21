"""Document intermediate representation with CP-aware direct formatting."""

from __future__ import annotations

from collections.abc import Callable, Sequence
from dataclasses import dataclass, field, replace
from enum import StrEnum

from ..diagnostics import ConversionReport, SourceLocation


_MAX_TABLE_DEPTH = 64


class BreakType(StrEnum):
    LINE = "line"
    PAGE = "page"


class SectionBreakType(StrEnum):
    CONTINUOUS = "continuous"
    NEXT_COLUMN = "nextColumn"
    NEXT_PAGE = "nextPage"
    EVEN_PAGE = "evenPage"
    ODD_PAGE = "oddPage"


@dataclass(slots=True, frozen=True)
class CharacterProperties:
    """Direct character properties; ``None`` means not specified by the DOC run."""

    style_id: int | None = None
    ascii_font: str | None = None
    high_ansi_font: str | None = None
    east_asia_font: str | None = None
    complex_script_font: str | None = None
    font_hint: str | None = None
    bold: bool | None = None
    complex_script_bold: bool | None = None
    italic: bool | None = None
    complex_script_italic: bool | None = None
    strike: bool | None = None
    double_strike: bool | None = None
    small_caps: bool | None = None
    caps: bool | None = None
    hidden: bool | None = None
    no_proof: bool | None = None
    underline: str | None = None
    color: str | None = None
    highlight: str | None = None
    size_half_points: int | None = None
    complex_script_size_half_points: int | None = None
    kerning_half_points: int | None = None
    vertical_align: str | None = None
    position_half_points: int | None = None
    snap_to_grid: bool | None = None
    language: str | None = None
    east_asia_language: str | None = None
    complex_script_language: str | None = None


@dataclass(slots=True, frozen=True)
class BorderProperties:
    style: str
    size_eighth_points: int
    color: str = "auto"
    space_points: int = 0
    shadow: bool = False
    frame: bool = False


@dataclass(slots=True, frozen=True)
class TableBorders:
    top: BorderProperties | None = None
    left: BorderProperties | None = None
    bottom: BorderProperties | None = None
    right: BorderProperties | None = None
    inside_horizontal: BorderProperties | None = None
    inside_vertical: BorderProperties | None = None


@dataclass(slots=True, frozen=True)
class TableCellMargins:
    top: int | None = 0
    left: int | None = 108
    bottom: int | None = 0
    right: int | None = 108


@dataclass(slots=True, frozen=True)
class ShadingProperties:
    pattern: str
    foreground: str = "auto"
    background: str = "auto"


@dataclass(slots=True, frozen=True)
class TableCellMarginOverride:
    first_cell: int
    limit_cell: int
    sides: tuple[str, ...]
    width_twips: int | None


@dataclass(slots=True, frozen=True)
class TableCellDefinition:
    preferred_width_twips: int | None = None
    horizontal_merge: str | None = None
    vertical_merge: str | None = None
    vertical_alignment: str | None = None
    fit_text: bool | None = None
    no_wrap: bool | None = None
    borders: TableBorders = field(default_factory=TableBorders)


@dataclass(slots=True, frozen=True)
class TableRowProperties:
    cell_boundaries_twips: tuple[int, ...] = ()
    cell_definitions: tuple[TableCellDefinition, ...] = ()
    alignment: str | None = None
    left_indent_twips: int | None = None
    gap_half_twips: int | None = None
    height_twips: int | None = None
    height_rule: str | None = None
    cant_split: bool | None = None
    is_header: bool | None = None
    borders: TableBorders = field(default_factory=TableBorders)
    default_cell_margins: TableCellMargins = field(
        default_factory=TableCellMargins
    )
    cell_margin_overrides: tuple[TableCellMarginOverride, ...] = ()
    cell_shadings: tuple[ShadingProperties | None, ...] = ()


@dataclass(slots=True, frozen=True)
class ParagraphProperties:
    """Direct paragraph properties represented in WordprocessingML units."""

    style_id: int | None = None
    justification: str | None = None
    keep_lines: bool | None = None
    keep_next: bool | None = None
    page_break_before: bool | None = None
    widow_control: bool | None = None
    kinsoku: bool | None = None
    word_wrap: bool | None = None
    overflow_punctuation: bool | None = None
    top_line_punctuation: bool | None = None
    auto_space_east_asian_latin: bool | None = None
    auto_space_east_asian_numbers: bool | None = None
    snap_to_grid: bool | None = None
    adjust_right_indent: bool | None = None
    left_indent_twips: int | None = None
    right_indent_twips: int | None = None
    first_line_indent_twips: int | None = None
    space_before_twips: int | None = None
    space_after_twips: int | None = None
    line_spacing_twips: int | None = None
    line_rule: str | None = None
    in_table: bool | None = None
    table_depth: int | None = None
    table_terminating: bool | None = None
    inner_table_cell: bool | None = None
    inner_table_row: bool | None = None
    table_row: TableRowProperties | None = None

    @property
    def effective_table_depth(self) -> int:
        if self.table_depth is not None:
            return max(self.table_depth, 0)
        return 1 if self.in_table else 0


@dataclass(slots=True, frozen=True)
class FontDefinition:
    """One font from the DOC SttbfFfn table."""

    index: int
    name: str
    alternate_name: str | None = None
    charset: int = 0
    family: str | None = None
    pitch: str | None = None
    weight: int | None = None
    panose: bytes = b""
    signature: bytes = b""


@dataclass(slots=True, frozen=True)
class StyleDefinition:
    """A paragraph or character style, retaining its DOC style-table index."""

    index: int
    name: str
    kind: str
    based_on: int | None = None
    next_style: int | None = None
    paragraph_properties: ParagraphProperties = field(
        default_factory=ParagraphProperties
    )
    character_properties: CharacterProperties = field(
        default_factory=CharacterProperties
    )

    @property
    def ooxml_style_id(self) -> str:
        return f"DocStyle{self.index}"


@dataclass(slots=True, frozen=True)
class StyleSheet:
    """Parsed style definitions plus resolved properties used for toggles."""

    styles: tuple[StyleDefinition | None, ...] = ()
    default_character_properties: CharacterProperties = field(
        default_factory=CharacterProperties
    )
    effective_character_properties: tuple[CharacterProperties | None, ...] = ()

    def style_at(self, index: int | None) -> StyleDefinition | None:
        if index is None or index < 0 or index >= len(self.styles):
            return None
        return self.styles[index]

    def effective_character_at(self, index: int | None) -> CharacterProperties:
        if (
            index is not None
            and 0 <= index < len(self.effective_character_properties)
            and self.effective_character_properties[index] is not None
        ):
            value = self.effective_character_properties[index]
            assert value is not None
            return value
        return self.default_character_properties


@dataclass(slots=True, frozen=True)
class StoryCharacter:
    """One decoded character and its half-open MS-DOC CP range."""

    text: str
    cp_start: int
    cp_end: int


@dataclass(slots=True, frozen=True)
class TextRun:
    text: str
    properties: CharacterProperties = field(default_factory=CharacterProperties)


@dataclass(slots=True, frozen=True)
class Tab:
    properties: CharacterProperties = field(default_factory=CharacterProperties)


@dataclass(slots=True, frozen=True)
class Break:
    kind: BreakType
    properties: CharacterProperties = field(default_factory=CharacterProperties)


@dataclass(slots=True, frozen=True)
class Field:
    """A live Word field whose cached result remains available for display."""

    instruction: str
    result: tuple["Inline", ...] = ()
    properties: CharacterProperties = field(default_factory=CharacterProperties)


@dataclass(slots=True, frozen=True)
class FloatingTextBox:
    """A positioned header/footer textbox reconstructed from a DOC Spa."""

    shape_id: int
    anchor_cp: int
    left_twips: int
    top_twips: int
    width_twips: int
    height_twips: int
    horizontal_relative: str
    vertical_relative: str
    wrap_type: str
    wrap_side: str
    behind_text: bool
    anchor_locked: bool
    paragraphs: tuple["Paragraph", ...]
    blocks: tuple["Paragraph | Table", ...] = ()

    @property
    def body_blocks(self) -> tuple["Paragraph | Table", ...]:
        return self.blocks or self.paragraphs


Inline = TextRun | Tab | Break | Field | FloatingTextBox


@dataclass(slots=True, frozen=True)
class SectionProperties:
    """Resolved page layout for one half-open main-story CP range."""

    cp_start: int
    cp_end: int
    break_type: SectionBreakType = SectionBreakType.NEXT_PAGE
    page_width_twips: int = 12240
    page_height_twips: int = 15840
    orientation: str = "portrait"
    margin_top_twips: int = 1440
    margin_right_twips: int = 1440
    margin_bottom_twips: int = 1440
    margin_left_twips: int = 1440
    header_distance_twips: int = 720
    footer_distance_twips: int = 720
    gutter_twips: int = 0
    title_page: bool = False
    document_grid_type: str | None = None
    document_grid_line_pitch_twips: int | None = None
    document_grid_character_space: int | None = None
    even_header: HeaderFooterStory | None = None
    default_header: HeaderFooterStory | None = None
    even_footer: HeaderFooterStory | None = None
    default_footer: HeaderFooterStory | None = None
    first_header: HeaderFooterStory | None = None
    first_footer: HeaderFooterStory | None = None


@dataclass(slots=True, frozen=True)
class Paragraph:
    inlines: tuple[Inline, ...]
    properties: ParagraphProperties = field(default_factory=ParagraphProperties)
    section_end: SectionProperties | None = None


@dataclass(slots=True, frozen=True)
class TableCell:
    paragraphs: tuple[Paragraph, ...]
    width_twips: int | None = None
    grid_span: int = 1
    vertical_merge: str | None = None
    vertical_alignment: str | None = None
    fit_text: bool | None = None
    no_wrap: bool | None = None
    borders: TableBorders = field(default_factory=TableBorders)
    margins: TableCellMargins = field(default_factory=TableCellMargins)
    shading: ShadingProperties | None = None
    blocks: tuple[Paragraph | Table, ...] = ()

    @property
    def body_blocks(self) -> tuple[Paragraph | Table, ...]:
        return self.blocks or self.paragraphs


@dataclass(slots=True, frozen=True)
class TableRow:
    cells: tuple[TableCell, ...]
    properties: TableRowProperties = field(default_factory=TableRowProperties)


@dataclass(slots=True, frozen=True)
class Table:
    rows: tuple[TableRow, ...]


Block = Paragraph | Table


@dataclass(slots=True, frozen=True)
class HeaderFooterStory:
    """One non-empty header/footer story after removing its guard paragraph."""

    cp_start: int
    cp_end: int
    paragraphs: tuple[Paragraph, ...]
    blocks: tuple[Block, ...] = ()

    @property
    def body_blocks(self) -> tuple[Block, ...]:
        return self.blocks or self.paragraphs


@dataclass(slots=True, frozen=True)
class Document:
    paragraphs: tuple[Paragraph, ...]
    fonts: tuple[FontDefinition, ...] = ()
    styles: StyleSheet = field(default_factory=StyleSheet)
    blocks: tuple[Block, ...] = ()
    sections: tuple[SectionProperties, ...] = ()
    even_and_odd_headers: bool = False
    adjust_line_height_in_table: bool | None = None

    @property
    def body_blocks(self) -> tuple[Block, ...]:
        return self.blocks or self.paragraphs


@dataclass(slots=True, frozen=True)
class _TableMarker:
    kind: str
    properties: ParagraphProperties


@dataclass(slots=True)
class _TableContext:
    depth: int
    rows: list[TableRow] = field(default_factory=list)
    raw_cells: list[tuple[Block, ...]] = field(default_factory=list)
    cell_blocks: list[Block] = field(default_factory=list)


@dataclass(slots=True)
class _FieldContext:
    instruction: list[str]
    result: list[Inline]
    properties: CharacterProperties
    has_separator: bool = False


def _replace_margin_sides(
    margins: TableCellMargins,
    sides: tuple[str, ...],
    value: int | None,
) -> TableCellMargins:
    changes = {side: value for side in sides}
    return replace(margins, **changes)


def _cell_margins(
    properties: TableRowProperties,
    cell_index: int,
) -> TableCellMargins:
    defaults = properties.default_cell_margins
    margins = defaults
    for override in properties.cell_margin_overrides:
        if override.first_cell <= cell_index < override.limit_cell:
            for side in override.sides:
                value = override.width_twips
                if value is None:
                    value = getattr(defaults, side)
                margins = _replace_margin_sides(margins, (side,), value)
    return margins


def _build_table_row(
    raw_cells: list[tuple[Block, ...]],
    properties: TableRowProperties,
    report: ConversionReport,
) -> TableRow:
    definitions = properties.cell_definitions
    boundaries = properties.cell_boundaries_twips
    if definitions and len(definitions) != len(raw_cells):
        report.warning(
            "TABLE_CELL_DEFINITION_MISMATCH",
            "table row cell markers do not match its TDefTable definitions",
            cell_count=len(raw_cells),
            definition_count=len(definitions),
        )
    elif boundaries and len(boundaries) != len(raw_cells) + 1:
        report.warning(
            "TABLE_GRID_MISMATCH",
            "table row cell markers do not match its column boundaries",
            cell_count=len(raw_cells),
            boundary_count=len(boundaries),
        )

    cells: list[TableCell] = []
    for index, cell_blocks in enumerate(raw_cells):
        definition = (
            definitions[index] if index < len(definitions) else TableCellDefinition()
        )
        grid_width = (
            boundaries[index + 1] - boundaries[index]
            if index + 1 < len(boundaries)
            else None
        )
        width = definition.preferred_width_twips
        if width is None and grid_width is not None and grid_width >= 0:
            width = grid_width
        content_blocks = cell_blocks or (Paragraph(()),)
        cell = TableCell(
            paragraphs=tuple(
                block for block in content_blocks if isinstance(block, Paragraph)
            ),
            width_twips=width,
            vertical_merge=definition.vertical_merge,
            vertical_alignment=definition.vertical_alignment,
            fit_text=definition.fit_text,
            no_wrap=definition.no_wrap,
            borders=definition.borders,
            margins=_cell_margins(properties, index),
            shading=(
                properties.cell_shadings[index]
                if index < len(properties.cell_shadings)
                else None
            ),
            blocks=content_blocks,
        )
        if definition.horizontal_merge == "continue" and cells:
            previous = cells[-1]
            merged_width = (
                (previous.width_twips or 0) + (cell.width_twips or 0)
                if previous.width_twips is not None or cell.width_twips is not None
                else None
            )
            cells[-1] = replace(
                previous,
                width_twips=merged_width,
                grid_span=previous.grid_span + 1,
            )
        else:
            cells.append(cell)
    return TableRow(tuple(cells), properties)


def _assemble_table_blocks(
    flow: list[Paragraph | _TableMarker],
    report: ConversionReport,
) -> tuple[Block, ...]:
    blocks: list[Block] = []
    contexts: list[_TableContext] = []
    malformed_groups = 0
    limited_depth_items = 0

    def emit_completed_context(context: _TableContext) -> None:
        nonlocal malformed_groups
        completed: list[Block] = []
        if context.rows:
            completed.append(Table(tuple(context.rows)))
        if context.raw_cells or context.cell_blocks:
            malformed_groups += 1
            for cell_blocks in context.raw_cells:
                completed.extend(cell_blocks)
            completed.extend(context.cell_blocks)
        if contexts:
            contexts[-1].cell_blocks.extend(completed)
        else:
            blocks.extend(completed)

    def close_deeper_than(depth: int) -> None:
        while len(contexts) > depth:
            emit_completed_context(contexts.pop())

    def context_at(depth: int) -> _TableContext:
        nonlocal malformed_groups
        if depth > len(contexts) + 1:
            malformed_groups += 1
        while len(contexts) < depth:
            contexts.append(_TableContext(len(contexts) + 1))
        return contexts[depth - 1]

    for item in flow:
        raw_depth = item.properties.effective_table_depth
        depth = min(raw_depth, _MAX_TABLE_DEPTH)
        if raw_depth > _MAX_TABLE_DEPTH:
            limited_depth_items += 1
        if isinstance(item, Paragraph):
            close_deeper_than(depth)
            if depth == 0:
                close_deeper_than(0)
                blocks.append(item)
            else:
                context_at(depth).cell_blocks.append(item)
            continue

        if depth == 0:
            continue
        close_deeper_than(depth)
        context = context_at(depth)
        if item.kind == "cell":
            context.raw_cells.append(
                tuple(context.cell_blocks) or (Paragraph(()),)
            )
            context.cell_blocks.clear()
        elif item.kind == "row":
            if context.cell_blocks:
                context.raw_cells.append(tuple(context.cell_blocks))
                context.cell_blocks.clear()
            if not context.raw_cells:
                malformed_groups += 1
                continue
            row_properties = item.properties.table_row or TableRowProperties()
            context.rows.append(
                _build_table_row(context.raw_cells, row_properties, report)
            )
            context.raw_cells.clear()

    close_deeper_than(0)
    if limited_depth_items:
        report.warning(
            "TABLE_DEPTH_LIMITED",
            "table nesting exceeded the safe reconstruction depth",
            maximum_depth=_MAX_TABLE_DEPTH,
            item_count=limited_depth_items,
        )
    if malformed_groups:
        report.warning(
            "MALFORMED_TABLE_FLATTENED",
            "incomplete table marker sequences were preserved as paragraphs",
            group_count=malformed_groups,
        )
    return tuple(blocks)


def _is_xml_character(character: str) -> bool:
    value = ord(character)
    return (
        value in (0x09, 0x0A, 0x0D)
        or 0x20 <= value <= 0xD7FF
        or 0xE000 <= value <= 0xFFFD
        or 0x10000 <= value <= 0x10FFFF
    ) and value not in (0xFFFE, 0xFFFF)


def parse_main_story(
    text: str | Sequence[StoryCharacter],
    report: ConversionReport,
    *,
    character_properties_at: Callable[[int], CharacterProperties] | None = None,
    paragraph_properties_at: Callable[[int], ParagraphProperties] | None = None,
    floating_textbox_at: Callable[[int], FloatingTextBox | None] | None = None,
    sections: Sequence[SectionProperties] = (),
    story_name: str = "main",
) -> Document:
    if isinstance(text, str):
        characters = tuple(
            StoryCharacter(character, cp, cp + 1)
            for cp, character in enumerate(text)
        )
    else:
        characters = tuple(text)

    default_character_properties = CharacterProperties()
    default_paragraph_properties = ParagraphProperties()

    paragraphs: list[Paragraph] = []
    flow: list[Paragraph | _TableMarker] = []
    inlines: list[Inline] = []
    text_buffer: list[str] = []
    text_properties = default_character_properties
    unsupported_controls: dict[int, int] = {}
    deferred_markers: dict[str, int] = {}
    flattened_fields = 0
    field_stack: list[_FieldContext] = []
    last_was_terminator = False
    section_values = tuple(sections)
    internal_sections_by_end = {
        section.cp_end: section for section in section_values[:-1]
    }
    matched_section_ends: set[int] = set()

    def visible() -> bool:
        return all(context.has_separator for context in field_stack)

    def current_inlines() -> list[Inline]:
        return field_stack[-1].result if field_stack else inlines

    def extend_visible_inlines(values: Sequence[Inline]) -> None:
        target = current_inlines()
        for value in values:
            if (
                target
                and isinstance(target[-1], TextRun)
                and isinstance(value, TextRun)
                and target[-1].properties == value.properties
            ):
                previous = target[-1]
                assert isinstance(previous, TextRun)
                target[-1] = TextRun(
                    previous.text + value.text,
                    previous.properties,
                )
            else:
                target.append(value)

    def flush_text() -> None:
        if text_buffer:
            buffered_text = "".join(text_buffer)
            if (
                current_inlines()
                and isinstance(current_inlines()[-1], TextRun)
                and current_inlines()[-1].properties == text_properties
            ):
                previous = current_inlines()[-1]
                assert isinstance(previous, TextRun)
                current_inlines()[-1] = TextRun(
                    previous.text + buffered_text,
                    previous.properties,
                )
            else:
                current_inlines().append(TextRun(buffered_text, text_properties))
            text_buffer.clear()

    def append_text(character: str, properties: CharacterProperties) -> None:
        nonlocal text_properties
        if text_buffer and properties != text_properties:
            flush_text()
        text_properties = properties
        text_buffer.append(character)

    def finish_paragraph(
        properties: ParagraphProperties,
        section_end: SectionProperties | None = None,
    ) -> None:
        flush_text()
        paragraph = Paragraph(tuple(inlines), properties, section_end)
        paragraphs.append(paragraph)
        flow.append(paragraph)
        inlines.clear()

    for unit in characters:
        character = unit.text
        cp_offset = unit.cp_start
        value = ord(character)
        character_properties = (
            character_properties_at(cp_offset)
            if character_properties_at is not None
            else default_character_properties
        )

        if value == 0x13:  # field begin
            if visible():
                flush_text()
            field_stack.append(
                _FieldContext([], [], character_properties)
            )
            continue
        if value == 0x14 and field_stack:  # field separator
            if visible():
                flush_text()
            field_stack[-1].has_separator = True
            continue
        if value == 0x15 and field_stack:  # field end
            if visible():
                flush_text()
            context = field_stack.pop()
            instruction = "".join(context.instruction)
            instruction_tokens = instruction.lstrip().split(maxsplit=1)
            field_type = instruction_tokens[0].upper() if instruction_tokens else ""
            parent_is_visible = visible()
            if field_type in {"PAGE", "NUMPAGES", "SECTIONPAGES"}:
                if parent_is_visible:
                    current_inlines().append(
                        Field(
                            instruction=instruction,
                            result=tuple(context.result),
                            properties=context.properties,
                        )
                    )
            else:
                if parent_is_visible:
                    extend_visible_inlines(context.result)
                flattened_fields += 1
            continue
        if not visible():
            for context in reversed(field_stack):
                if not context.has_separator:
                    context.instruction.append(character)
                    break
            continue

        if character == "\r":
            paragraph_properties = (
                paragraph_properties_at(cp_offset)
                if paragraph_properties_at is not None
                else default_paragraph_properties
            )
            if paragraph_properties.inner_table_row:
                if text_buffer or inlines:
                    finish_paragraph(paragraph_properties)
                flow.append(_TableMarker("row", paragraph_properties))
            elif paragraph_properties.inner_table_cell:
                finish_paragraph(paragraph_properties)
                flow.append(_TableMarker("cell", paragraph_properties))
            else:
                finish_paragraph(paragraph_properties)
            last_was_terminator = True
        elif character == "\t":
            flush_text()
            inlines.append(Tab(character_properties))
            last_was_terminator = False
        elif character in ("\n", "\v"):
            flush_text()
            inlines.append(Break(BreakType.LINE, character_properties))
            last_was_terminator = False
        elif character == "\f":
            section = internal_sections_by_end.get(unit.cp_end)
            if section is not None:
                paragraph_properties = (
                    paragraph_properties_at(cp_offset)
                    if paragraph_properties_at is not None
                    else default_paragraph_properties
                )
                finish_paragraph(paragraph_properties, section)
                matched_section_ends.add(section.cp_end)
                last_was_terminator = True
            else:
                flush_text()
                inlines.append(Break(BreakType.PAGE, character_properties))
                if not section_values:
                    deferred_markers["BREAK_KIND_APPROXIMATED"] = (
                        deferred_markers.get("BREAK_KIND_APPROXIMATED", 0) + 1
                    )
                last_was_terminator = False
        elif value == 0x07:
            paragraph_properties = (
                paragraph_properties_at(cp_offset)
                if paragraph_properties_at is not None
                else default_paragraph_properties
            )
            if paragraph_properties.effective_table_depth:
                if paragraph_properties.table_terminating:
                    if text_buffer or inlines:
                        finish_paragraph(paragraph_properties)
                    flow.append(_TableMarker("row", paragraph_properties))
                else:
                    finish_paragraph(paragraph_properties)
                    flow.append(_TableMarker("cell", paragraph_properties))
                last_was_terminator = True
            else:
                deferred_markers["TABLE_MARKER_DEFERRED"] = (
                    deferred_markers.get("TABLE_MARKER_DEFERRED", 0) + 1
                )
                append_text("\uFFFC", character_properties)
                last_was_terminator = False
        elif value in (0x01, 0x02, 0x08):
            textbox = (
                floating_textbox_at(cp_offset)
                if value == 0x08 and floating_textbox_at is not None
                else None
            )
            if textbox is not None:
                flush_text()
                current_inlines().append(textbox)
                last_was_terminator = False
                continue
            marker_code = {
                0x01: "OBJECT_ANCHOR_DEFERRED",
                0x02: "NOTE_REFERENCE_DEFERRED",
                0x08: "OBJECT_ANCHOR_DEFERRED",
            }[value]
            deferred_markers[marker_code] = deferred_markers.get(marker_code, 0) + 1
            append_text("\uFFFC", character_properties)
            last_was_terminator = False
        elif value < 0x20 or not _is_xml_character(character):
            unsupported_controls[value] = unsupported_controls.get(value, 0) + 1
            append_text("\uFFFD", character_properties)
            last_was_terminator = False
        else:
            append_text(character, character_properties)
            last_was_terminator = False

    if (
        text_buffer
        or inlines
        or not flow
        or not last_was_terminator
    ):
        paragraph_cp = characters[-1].cp_start if characters else 0
        paragraph_properties = (
            paragraph_properties_at(paragraph_cp)
            if paragraph_properties_at is not None
            else default_paragraph_properties
        )
        finish_paragraph(paragraph_properties)

    if field_stack:
        flattened_fields += len(field_stack)
        report.warning(
            "UNTERMINATED_FIELD",
            f"{story_name} story contains an unterminated field; its instruction was hidden",
            location=SourceLocation(
                story=story_name,
                cp_start=characters[0].cp_start if characters else 0,
                cp_end=characters[-1].cp_end if characters else 0,
            ),
            open_field_count=len(field_stack),
        )
    if flattened_fields:
        report.warning(
            "FIELDS_FLATTENED",
            "unsupported field structures were flattened to their displayed result",
            location=SourceLocation(story=story_name),
            field_count=flattened_fields,
        )
    unmatched_section_ends = sorted(
        set(internal_sections_by_end) - matched_section_ends
    )
    if unmatched_section_ends:
        report.warning(
            "SECTION_BOUNDARY_NOT_FOUND",
            "some PlcfSed section boundaries did not end at a section-mark character",
            location=SourceLocation(story=story_name),
            cp_ends=unmatched_section_ends,
        )
    for codepoint, count in sorted(unsupported_controls.items()):
        report.warning(
            "UNSUPPORTED_CONTROL_CHARACTER",
            f"unsupported control character U+{codepoint:04X} was replaced",
            location=SourceLocation(story=story_name),
            count=count,
        )
    deferred_messages = {
        "BREAK_KIND_APPROXIMATED": (
            "an ambiguous page/section marker was emitted as a page break because "
            "no matching section table entry was available"
        ),
        "OBJECT_ANCHOR_DEFERRED": (
            "picture or object anchor was emitted as an object replacement character"
        ),
        "NOTE_REFERENCE_DEFERRED": (
            "note reference was emitted as an object replacement character"
        ),
        "TABLE_MARKER_DEFERRED": (
            "table marker was emitted as an object replacement character"
        ),
    }
    for code, count in sorted(deferred_markers.items()):
        report.warning(
            code,
            deferred_messages[code],
            location=SourceLocation(story=story_name),
            count=count,
        )

    return Document(
        tuple(paragraphs),
        blocks=_assemble_table_blocks(flow, report),
        sections=section_values,
    )
