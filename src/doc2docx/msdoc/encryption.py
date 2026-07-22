"""Bounded decryption helpers for password-protected Word binary streams."""

from __future__ import annotations

from dataclasses import dataclass
import hashlib
import hmac
import struct

from ..errors import EncryptedDocumentError, InvalidWordDocument
from .fib import FibBase


_XOR_INITIAL_CODES = (
    0xE1F0, 0x1D0F, 0xCC9C, 0x84C0, 0x110C,
    0x0E10, 0xF1CE, 0x313E, 0x1872, 0xE139,
    0xD40F, 0x84F9, 0x280C, 0xA96A, 0x4EC3,
)

_XOR_MATRIX = (
    0xAEFC, 0x4DD9, 0x9BB2, 0x2745, 0x4E8A, 0x9D14, 0x2A09,
    0x7B61, 0xF6C2, 0xFDA5, 0xEB6B, 0xC6F7, 0x9DCF, 0x2BBF,
    0x4563, 0x8AC6, 0x05AD, 0x0B5A, 0x16B4, 0x2D68, 0x5AD0,
    0x0375, 0x06EA, 0x0DD4, 0x1BA8, 0x3750, 0x6EA0, 0xDD40,
    0xD849, 0xA0B3, 0x5147, 0xA28E, 0x553D, 0xAA7A, 0x44D5,
    0x6F45, 0xDE8A, 0xAD35, 0x4A4B, 0x9496, 0x390D, 0x721A,
    0xEB23, 0xC667, 0x9CEF, 0x29FF, 0x53FE, 0xA7FC, 0x5FD9,
    0x47D3, 0x8FA6, 0x0F6D, 0x1EDA, 0x3DB4, 0x7B68, 0xF6D0,
    0xB861, 0x60E3, 0xC1C6, 0x93AD, 0x377B, 0x6EF6, 0xDDEC,
    0x45A0, 0x8B40, 0x06A1, 0x0D42, 0x1A84, 0x3508, 0x6A10,
    0xAA51, 0x4483, 0x8906, 0x022D, 0x045A, 0x08B4, 0x1168,
    0x76B4, 0xED68, 0xCAF1, 0x85C3, 0x1BA7, 0x374E, 0x6E9C,
    0x3730, 0x6E60, 0xDCC0, 0xA9A1, 0x4363, 0x86C6, 0x1DAD,
    0x3331, 0x6662, 0xCCC4, 0x89A9, 0x0373, 0x06E6, 0x0DCC,
    0x1021, 0x2042, 0x4084, 0x8108, 0x1231, 0x2462, 0x48C4,
)

_XOR_PAD_ARRAY = (
    0xBB, 0xFF, 0xFF, 0xBA, 0xFF, 0xFF, 0xB9, 0x80,
    0x00, 0xBE, 0x0F, 0x00, 0xBF, 0x0F, 0x00,
)


@dataclass(slots=True, frozen=True)
class DecryptedWordStreams:
    word_document: bytes
    table: bytes
    data: bytes | None


def _password_bytes_method2(password: str) -> bytes:
    encoded = password.encode("utf-16le")
    result = bytearray()
    for index in range(0, len(encoded), 2):
        low, high = encoded[index : index + 2]
        result.append(low or high)
        if len(result) == 15:
            break
    return bytes(result)


def _password_verifier_method1(password: bytes) -> int:
    verifier = 0
    for value in reversed(bytes((len(password),)) + password):
        carry = 1 if verifier & 0x4000 else 0
        verifier = (((verifier << 1) & 0x7FFF) | carry) ^ value
    return verifier ^ 0xCE4B


def _xor_key_method1(password: bytes) -> int:
    if not password:
        return 0
    xor_key = _XOR_INITIAL_CODES[len(password) - 1]
    current = 0x68
    for original in reversed(password):
        value = original
        for _ in range(7):
            if value & 0x40:
                xor_key ^= _XOR_MATRIX[current]
            value <<= 1
            current -= 1
    return xor_key


def xor_password_verifier(password: str) -> int:
    """Return the 32-bit Method 2 verifier stored in FibBase.lKey."""

    encoded = _password_bytes_method2(password)
    return (_xor_key_method1(encoded) << 16) | _password_verifier_method1(encoded)


def _rotate_right(value: int) -> int:
    return ((value >> 1) | ((value & 1) << 7)) & 0xFF


def _xor_array_method2(password: str) -> bytes:
    encoded = _password_bytes_method2(password)
    verifier_high = _xor_key_method1(encoded)
    key_high = verifier_high >> 8
    key_low = verifier_high & 0xFF
    values = bytearray(encoded + bytes(_XOR_PAD_ARRAY[: 16 - len(encoded)]))
    for index in range(0, 16, 2):
        values[index] = _rotate_right(values[index] ^ key_low)
        values[index + 1] = _rotate_right(values[index + 1] ^ key_high)
    return bytes(values)


def xor_transform(data: bytes, password: str, *, clear_prefix: int = 0) -> bytes:
    """Apply symmetric Word XOR Method 2 at absolute stream positions."""

    if not 0 <= clear_prefix <= len(data):
        raise InvalidWordDocument("XOR clear prefix exceeds the stream")
    xor_array = _xor_array_method2(password)
    output = bytearray(data)
    for position in range(clear_prefix, len(output)):
        value = output[position]
        transformed = value ^ xor_array[position % 16]
        if value != 0 and transformed != 0:
            output[position] = transformed
    return bytes(output)


def _rc4(key: bytes, data: bytes) -> bytes:
    if not key:
        raise InvalidWordDocument("RC4 key must not be empty")
    state = list(range(256))
    j = 0
    for index in range(256):
        j = (j + state[index] + key[index % len(key)]) & 0xFF
        state[index], state[j] = state[j], state[index]
    output = bytearray(len(data))
    i = 0
    j = 0
    for position, value in enumerate(data):
        i = (i + 1) & 0xFF
        j = (j + state[i]) & 0xFF
        state[i], state[j] = state[j], state[i]
        output[position] = value ^ state[(state[i] + state[j]) & 0xFF]
    return bytes(output)


def _rc4_binary_key(password: str, salt: bytes, block: int) -> bytes:
    password_hash = hashlib.md5(password[:255].encode("utf-16le")).digest()
    salted = (password_hash[:5] + salt) * 16
    salt_hash = hashlib.md5(salted).digest()
    return hashlib.md5(salt_hash[:5] + struct.pack("<I", block)).digest()


def _rc4_transform_stream(data: bytes, password: str, salt: bytes) -> bytes:
    output = bytearray()
    for block, offset in enumerate(range(0, len(data), 512)):
        output.extend(
            _rc4(
                _rc4_binary_key(password, salt, block),
                data[offset : offset + 512],
            )
        )
    return bytes(output)


def _decrypt_classic_rc4(
    base: FibBase,
    *,
    password: str,
    word_document: bytes,
    table: bytes,
    data: bytes | None,
) -> DecryptedWordStreams:
    if not 52 <= base.l_key <= len(table):
        raise InvalidWordDocument("RC4 encryption header range is invalid")
    header = table[: base.l_key]
    salt = header[4:20]
    encrypted_verifier = header[20:36]
    encrypted_verifier_hash = header[36:52]
    if len(salt) != 16 or len(encrypted_verifier_hash) != 16:
        raise InvalidWordDocument("RC4 encryption header is truncated")
    verifier_data = _rc4(
        _rc4_binary_key(password, salt, 0),
        encrypted_verifier + encrypted_verifier_hash,
    )
    verifier = verifier_data[:16]
    if not hmac.compare_digest(hashlib.md5(verifier).digest(), verifier_data[16:]):
        raise EncryptedDocumentError("incorrect password for RC4-encrypted document")

    decrypted_word = bytearray(_rc4_transform_stream(word_document, password, salt))
    decrypted_word[:68] = word_document[:68]
    decrypted_table = bytearray(_rc4_transform_stream(table, password, salt))
    decrypted_table[: base.l_key] = table[: base.l_key]
    return DecryptedWordStreams(
        bytes(decrypted_word),
        bytes(decrypted_table),
        _rc4_transform_stream(data, password, salt) if data is not None else None,
    )


def _cryptoapi_rc4_key(
    password: str,
    salt: bytes,
    block: int,
    key_bits: int,
) -> bytes:
    password_hash = hashlib.sha1(salt + password[:255].encode("utf-16le")).digest()
    final_hash = hashlib.sha1(password_hash + struct.pack("<I", block)).digest()
    if key_bits == 40:
        return final_hash[:5] + b"\0" * 11
    return final_hash[: key_bits // 8]


def _cryptoapi_transform_stream(
    data: bytes,
    password: str,
    salt: bytes,
    key_bits: int,
) -> bytes:
    output = bytearray()
    for block, offset in enumerate(range(0, len(data), 512)):
        output.extend(
            _rc4(
                _cryptoapi_rc4_key(password, salt, block, key_bits),
                data[offset : offset + 512],
            )
        )
    return bytes(output)


def _decrypt_cryptoapi_rc4(
    base: FibBase,
    *,
    password: str,
    word_document: bytes,
    table: bytes,
    data: bytes | None,
) -> DecryptedWordStreams:
    if not 72 <= base.l_key <= len(table):
        raise InvalidWordDocument("RC4 CryptoAPI encryption header range is invalid")
    header = table[: base.l_key]
    major, minor, outer_flags, header_size = struct.unpack_from("<HHII", header)
    if minor != 2 or major not in (2, 3, 4):
        raise EncryptedDocumentError(
            f"unsupported RC4 CryptoAPI encryption version {major}.{minor}"
        )
    header_end = 12 + header_size
    if header_size < 32 or header_end > len(header) - 60:
        raise InvalidWordDocument("RC4 CryptoAPI EncryptionHeader is truncated")
    (
        flags,
        size_extra,
        algorithm_id,
        hash_algorithm_id,
        key_bits,
        provider_type,
        _reserved1,
        reserved2,
    ) = struct.unpack_from("<8I", header, 12)
    if flags != outer_flags or not flags & 0x04 or flags & 0x30:
        raise InvalidWordDocument("RC4 CryptoAPI flags are inconsistent")
    if size_extra != 0 or algorithm_id not in (0, 0x6801):
        raise EncryptedDocumentError("unsupported CryptoAPI encryption algorithm")
    if hash_algorithm_id not in (0, 0x8004):
        raise EncryptedDocumentError("unsupported CryptoAPI hash algorithm")
    key_bits = key_bits or 40
    if not 40 <= key_bits <= 128 or key_bits % 8:
        raise InvalidWordDocument("RC4 CryptoAPI key size is invalid")
    if provider_type not in (0, 1) or reserved2 != 0:
        raise InvalidWordDocument("RC4 CryptoAPI provider fields are invalid")

    verifier_offset = header_end
    salt_size = struct.unpack_from("<I", header, verifier_offset)[0]
    if salt_size != 16:
        raise InvalidWordDocument("RC4 CryptoAPI salt must contain 16 bytes")
    salt = header[verifier_offset + 4 : verifier_offset + 20]
    encrypted_verifier = header[verifier_offset + 20 : verifier_offset + 36]
    verifier_hash_size = struct.unpack_from("<I", header, verifier_offset + 36)[0]
    encrypted_verifier_hash = header[verifier_offset + 40 : verifier_offset + 60]
    if verifier_hash_size != 20 or len(encrypted_verifier_hash) != 20:
        raise InvalidWordDocument("RC4 CryptoAPI verifier hash size is invalid")
    verifier_data = _rc4(
        _cryptoapi_rc4_key(password, salt, 0, key_bits),
        encrypted_verifier + encrypted_verifier_hash,
    )
    verifier = verifier_data[:16]
    if not hmac.compare_digest(hashlib.sha1(verifier).digest(), verifier_data[16:]):
        raise EncryptedDocumentError(
            "incorrect password for RC4 CryptoAPI-encrypted document"
        )

    decrypted_word = bytearray(
        _cryptoapi_transform_stream(word_document, password, salt, key_bits)
    )
    decrypted_word[:68] = word_document[:68]
    decrypted_table = bytearray(
        _cryptoapi_transform_stream(table, password, salt, key_bits)
    )
    decrypted_table[: base.l_key] = table[: base.l_key]
    return DecryptedWordStreams(
        bytes(decrypted_word),
        bytes(decrypted_table),
        (
            _cryptoapi_transform_stream(data, password, salt, key_bits)
            if data is not None
            else None
        ),
    )


def _decrypt_binary_rc4(
    base: FibBase,
    *,
    password: str,
    word_document: bytes,
    table: bytes,
    data: bytes | None,
) -> DecryptedWordStreams:
    if base.l_key < 4 or base.l_key > len(table):
        raise InvalidWordDocument("encryption header range is invalid")
    version = struct.unpack_from("<HH", table)[0:2]
    if version == (1, 1):
        return _decrypt_classic_rc4(
            base,
            password=password,
            word_document=word_document,
            table=table,
            data=data,
        )
    if version[1] == 2 and version[0] in (2, 3, 4):
        return _decrypt_cryptoapi_rc4(
            base,
            password=password,
            word_document=word_document,
            table=table,
            data=data,
        )
    raise EncryptedDocumentError(
        f"unsupported Word encryption version {version[0]}.{version[1]}"
    )


def decrypt_word_streams(
    base: FibBase,
    *,
    password: str | None,
    word_document: bytes,
    table: bytes,
    data: bytes | None,
) -> DecryptedWordStreams:
    if not base.is_encrypted:
        return DecryptedWordStreams(word_document, table, data)
    if password is None:
        raise EncryptedDocumentError(
            "password-protected Word document; provide a password"
        )
    if not base.is_obfuscated:
        return _decrypt_binary_rc4(
            base,
            password=password,
            word_document=word_document,
            table=table,
            data=data,
        )
    if xor_password_verifier(password) != base.l_key:
        raise EncryptedDocumentError("incorrect password for XOR-obfuscated document")
    return DecryptedWordStreams(
        xor_transform(word_document, password, clear_prefix=68),
        xor_transform(table, password),
        xor_transform(data, password) if data is not None else None,
    )
