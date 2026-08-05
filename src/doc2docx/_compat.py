"""Compatibility helpers for supported Python versions."""

try:
    from enum import StrEnum
except ImportError:  # Python 3.10
    from enum import Enum

    class StrEnum(str, Enum):
        """Backport the string behavior of :class:`enum.StrEnum`."""

        __str__ = str.__str__
        __format__ = str.__format__


__all__ = ["StrEnum"]
