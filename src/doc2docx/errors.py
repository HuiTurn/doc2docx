"""Domain-specific exceptions raised by the converter."""


class Doc2DocxError(Exception):
    """Base class for expected conversion failures."""


class BinaryBoundsError(Doc2DocxError):
    """A binary structure tried to read outside its declared bounds."""


class InvalidCompoundFile(Doc2DocxError):
    """The input is not a valid or safely readable CFB/OLE compound file."""


class StreamNotFound(InvalidCompoundFile):
    """A required stream is absent from the compound file."""


class InvalidWordDocument(Doc2DocxError):
    """The compound file is not a supported MS-DOC Word document."""


class EncryptedDocumentError(Doc2DocxError):
    """The input requires a password/decryption implementation."""


class UnsupportedFeatureError(Doc2DocxError):
    """A valid feature is outside the currently supported milestone."""


class PackageWriteError(Doc2DocxError):
    """The DOCX package could not be generated safely."""


class UnsafeOutputPathError(Doc2DocxError):
    """The requested destination could overwrite the source or is not DOCX."""
