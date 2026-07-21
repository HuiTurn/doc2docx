"""Public API for doc2docx."""

from .converter import ConversionResult, convert, inspect_doc

__all__ = ["ConversionResult", "convert", "inspect_doc"]
__version__ = "0.28.0"
