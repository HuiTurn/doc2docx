"""Structured diagnostics emitted during inspection and conversion."""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from enum import StrEnum
import json
import os
from pathlib import Path
import tempfile
from typing import Any


def write_json_file(path: str | Path, value: Any) -> None:
    """Atomically replace a UTF-8 JSON file in its destination directory."""

    destination = Path(path)
    destination.parent.mkdir(parents=True, exist_ok=True)
    content = json.dumps(value, ensure_ascii=False, indent=2) + "\n"
    descriptor, temporary_name = tempfile.mkstemp(
        dir=destination.parent,
        prefix=f".{destination.name}.",
        suffix=".tmp",
    )
    temporary = Path(temporary_name)
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8", newline="\n") as stream:
            stream.write(content)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, destination)
    except BaseException:
        temporary.unlink(missing_ok=True)
        raise


class Severity(StrEnum):
    INFO = "info"
    WARNING = "warning"
    ERROR = "error"


@dataclass(slots=True, frozen=True)
class SourceLocation:
    story: str | None = None
    cp_start: int | None = None
    cp_end: int | None = None
    stream: str | None = None
    fc_start: int | None = None
    fc_end: int | None = None


@dataclass(slots=True, frozen=True)
class Diagnostic:
    severity: Severity
    code: str
    message: str
    location: SourceLocation | None = None
    details: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        result = asdict(self)
        result["severity"] = self.severity.value
        if self.location is None:
            result.pop("location")
        if not self.details:
            result.pop("details")
        return result


@dataclass(slots=True)
class ConversionReport:
    source: str
    destination: str | None = None
    diagnostics: list[Diagnostic] = field(default_factory=list)
    statistics: dict[str, int | str | bool] = field(default_factory=dict)

    def add(
        self,
        severity: Severity,
        code: str,
        message: str,
        *,
        location: SourceLocation | None = None,
        **details: Any,
    ) -> None:
        self.diagnostics.append(
            Diagnostic(severity, code, message, location, details)
        )

    def info(self, code: str, message: str, **details: Any) -> None:
        self.add(Severity.INFO, code, message, **details)

    def warning(
        self,
        code: str,
        message: str,
        *,
        location: SourceLocation | None = None,
        **details: Any,
    ) -> None:
        self.add(
            Severity.WARNING,
            code,
            message,
            location=location,
            **details,
        )

    def error(self, code: str, message: str, **details: Any) -> None:
        self.add(Severity.ERROR, code, message, **details)

    @property
    def warnings(self) -> list[Diagnostic]:
        return [d for d in self.diagnostics if d.severity is Severity.WARNING]

    def to_dict(self) -> dict[str, Any]:
        return {
            "source": self.source,
            "destination": self.destination,
            "statistics": dict(self.statistics),
            "diagnostics": [item.to_dict() for item in self.diagnostics],
        }

    def write_json(self, path: str | Path) -> None:
        write_json_file(path, self.to_dict())
