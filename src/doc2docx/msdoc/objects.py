"""Extraction of embedded OLE ObjectPool storages from binary Word files."""

from __future__ import annotations

from collections.abc import Callable, Iterable, Mapping
from dataclasses import dataclass

from ..cfb import CompoundFile, ObjectType
from ..diagnostics import ConversionReport, SourceLocation
from ..errors import InvalidCompoundFile, StreamNotFound
from ..model import CharacterProperties, EmbeddedObject, StoryCharacter


@dataclass(slots=True, frozen=True)
class EmbeddedObjectCollection:
    objects: tuple[EmbeddedObject, ...] = ()
    by_separator_cp: Mapping[int, EmbeddedObject] | None = None

    def object_at(self, cp: int) -> EmbeddedObject | None:
        return (self.by_separator_cp or {}).get(cp)


def _object_pool_storages(compound: CompoundFile) -> dict[int, str]:
    storages: dict[int, str] = {}
    for entry in compound.entries:
        if entry.object_type is not ObjectType.STORAGE:
            continue
        parent, separator, name = entry.path.rpartition("/")
        if separator and parent == "ObjectPool" and name.startswith("_"):
            try:
                storage_id = int(name[1:], 10)
            except ValueError:
                continue
            if storage_id >= 0:
                storages.setdefault(storage_id, entry.path)
    return storages


def read_embedded_objects(
    compound: CompoundFile,
    characters: Iterable[StoryCharacter],
    *,
    report: ConversionReport,
    character_properties_at: Callable[[int], CharacterProperties],
) -> EmbeddedObjectCollection:
    """Match story field separators to ObjectPool storages by picture location."""

    storages = _object_pool_storages(compound)
    if not storages:
        return EmbeddedObjectCollection()

    anchors: list[tuple[int, int, CharacterProperties]] = []
    missing_storage_ids: set[int] = set()
    for character in characters:
        if character.text != "\x14":
            continue
        properties = character_properties_at(character.cp_start)
        storage_id = properties.picture_location
        if storage_id is None:
            continue
        if storage_id not in storages:
            missing_storage_ids.add(storage_id)
            continue
        anchors.append((character.cp_start, storage_id, properties))

    for storage_id in sorted(missing_storage_ids):
        report.warning(
            "OLE_OBJECT_STORAGE_MISSING",
            "an OLE field anchor references a missing ObjectPool storage",
            location=SourceLocation(story="main"),
            storage_id=storage_id,
        )

    exported: dict[int, bytes] = {}
    omitted_storage_ids: set[int] = set()
    objects: list[EmbeddedObject] = []
    by_cp: dict[int, EmbeddedObject] = {}
    for cp, storage_id, properties in anchors:
        if storage_id not in exported and storage_id not in omitted_storage_ids:
            try:
                exported[storage_id] = compound.export_storage(storages[storage_id])
            except (InvalidCompoundFile, StreamNotFound) as exc:
                omitted_storage_ids.add(storage_id)
                report.warning(
                    "OLE_OBJECT_OMITTED",
                    "an embedded OLE storage could not be safely reconstructed",
                    location=SourceLocation(story="main", cp_start=cp, cp_end=cp + 1),
                    storage_id=storage_id,
                    reason=str(exc),
                )
        data = exported.get(storage_id)
        if data is None:
            continue
        value = EmbeddedObject(
            object_id=len(objects) + 1,
            storage_id=storage_id,
            data=data,
            properties=properties,
        )
        objects.append(value)
        by_cp[cp] = value

    anchored_storage_ids = {storage_id for _, storage_id, _ in anchors}
    unanchored = sorted(set(storages) - anchored_storage_ids)
    if unanchored:
        report.warning(
            "OLE_OBJECTS_UNANCHORED",
            "ObjectPool storages without a confirmed field anchor were omitted",
            location=SourceLocation(stream="ObjectPool"),
            object_count=len(unanchored),
            storage_ids=unanchored,
        )
    return EmbeddedObjectCollection(tuple(objects), by_cp)
