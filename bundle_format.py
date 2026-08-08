# Copyright 2026 Julien Bombled
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#     http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.
"""Streaming writer and verifier for the Cortex portable bundle container."""

from __future__ import annotations

import hashlib
import io
import json
import struct
import tarfile
from collections.abc import Callable, Iterable, Mapping
from dataclasses import dataclass
from typing import BinaryIO, cast

from cryptography.exceptions import InvalidTag, UnsupportedAlgorithm
from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from cryptography.hazmat.primitives.kdf.argon2 import Argon2id
from pydantic import BaseModel, ValidationError

from bundle_contract import (
    BUNDLE_CONTRACT_VERSION,
    CONTAINER_VERSION,
    FRAME_BYTES,
    MAX_ENCRYPTED_FRAME_BYTES,
    MAX_HEADER_BYTES,
    MAX_MANIFEST_BYTES,
    NONCE_PREFIX_BYTES,
    ROLE_ORDER,
    SALT_BYTES,
    BundleErrorCode,
    BundleHeader,
    BundleManifest,
    BundleMember,
    BundleRole,
    EmbeddingFingerprint,
    IndexContracts,
    decode_canonical_base64,
    local_index_contracts,
)
from index_contract import build_embedding_fingerprint

MAGIC = b"CORTEXBUNDLE"
_CONTAINER_PREFIX_BYTES = len(MAGIC) + 4
_LENGTH_BYTES = 4
_GCM_TAG_BYTES = 16
_KEY_BYTES = 32
_AAD_FINAL = b"\x01"
_AAD_CURRENT = b"\x00"
_MANIFEST_NAME = "manifest.json"
_ROLE_PREFIX = "roles"
_STREAM_BLOCK_BYTES = 64 * 1024


class BundleFormatError(RuntimeError):
    """One classified bundle failure safe for the machine error contract."""

    def __init__(
        self,
        code: BundleErrorCode,
        phase: str,
        *,
        header_matches_manifest: bool | None = None,
    ) -> None:
        self.code = code
        self.phase = phase
        self.header_matches_manifest = header_matches_manifest
        super().__init__(code)


@dataclass(frozen=True)
class BundleMemberSource:
    """Re-openable streamed content for one member already declared by a manifest."""

    role: BundleRole
    path: str
    bytes: int
    sha256: str
    opener: Callable[[], BinaryIO]


@dataclass(frozen=True)
class BundleVerification:
    """Successful authenticated result returned by the format verifier."""

    header: BundleHeader
    manifest: BundleManifest
    compatible: bool


def canonical_json_bytes(value: BaseModel | Mapping[str, object] | list[object]) -> bytes:
    """Serialize one wire value as compact key-sorted UTF-8 JSON."""
    if isinstance(value, BaseModel):
        payload = value.model_dump(mode="json")
    else:
        payload = value
    return json.dumps(
        payload,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
    ).encode("utf-8")


def _manifest_json_bytes(manifest: BundleManifest) -> bytes:
    """Serialize the manifest while preserving canonical role-key order."""
    return json.dumps(
        manifest.model_dump(mode="json"),
        sort_keys=False,
        separators=(",", ":"),
        ensure_ascii=False,
    ).encode("utf-8")


def compute_members_digest(members: Iterable[BundleMember]) -> str:
    """Return the canonical digest of one role's ordered member declarations."""
    payload = [item.model_dump(mode="json") for item in members]
    return hashlib.sha256(canonical_json_bytes(payload)).hexdigest()


def build_local_fingerprint(fastembed_version: str) -> EmbeddingFingerprint:
    """Build the local fingerprint without importing resolved user configuration."""
    return cast(
        EmbeddingFingerprint,
        EmbeddingFingerprint.model_validate(build_embedding_fingerprint(fastembed_version)),
    )


def is_compatible(
    contracts: IndexContracts,
    fingerprint: EmbeddingFingerprint,
    fastembed_version: str,
) -> bool:
    """Compare authenticated or claimed values with the current local product."""
    return contracts == local_index_contracts() and fingerprint == build_local_fingerprint(
        fastembed_version
    )


def _aad(header_digest: bytes, frame_index: int, final: bool) -> bytes:
    return header_digest + frame_index.to_bytes(8, "big") + (
        _AAD_FINAL if final else _AAD_CURRENT
    )


def _nonce(prefix: bytes, frame_index: int) -> bytes:
    return prefix + frame_index.to_bytes(8, "big")


def _derive_key(password: str, header: BundleHeader) -> bytes:
    salt = decode_canonical_base64(header.kdf.salt, SALT_BYTES)
    try:
        kdf = Argon2id(
            salt=salt,
            length=_KEY_BYTES,
            iterations=header.kdf.iterations,
            lanes=header.kdf.lanes,
            memory_cost=header.kdf.memory_cost,
        )
    except UnsupportedAlgorithm as exc:
        raise BundleFormatError("kdf_unavailable", "derive_key") from exc
    try:
        return cast(bytes, kdf.derive(password.encode("utf-8")))
    except UnsupportedAlgorithm as exc:
        raise BundleFormatError("kdf_unavailable", "derive_key") from exc


class _FrameEncryptingWriter(io.RawIOBase):
    def __init__(self, output: BinaryIO, key: bytes, header: BundleHeader, header_bytes: bytes):
        self._output = output
        self._aead = AESGCM(key)
        self._prefix = decode_canonical_base64(
            header.cipher.nonce_prefix,
            NONCE_PREFIX_BYTES,
        )
        self._header_digest = hashlib.sha256(header_bytes).digest()
        self._buffer = bytearray()
        self._frame_index = 0
        self._finalized = False

    def writable(self) -> bool:
        return True

    def write(self, data: bytes | bytearray) -> int:  # type: ignore[override]
        if self._finalized:
            raise ValueError("bundle payload writer is finalized")
        raw = bytes(data)
        self._buffer.extend(raw)
        while len(self._buffer) > FRAME_BYTES:
            plaintext = bytes(self._buffer[:FRAME_BYTES])
            del self._buffer[:FRAME_BYTES]
            self._emit(plaintext, final=False)
        return len(raw)

    def finalize(self) -> None:
        """Emit the one retained frame with its authenticated final marker."""
        if self._finalized:
            return
        if not self._buffer:
            raise BundleFormatError("malformed_payload", "write_payload")
        self._emit(bytes(self._buffer), final=True)
        self._buffer.clear()
        self._finalized = True

    def _emit(self, plaintext: bytes, *, final: bool) -> None:
        encrypted = self._aead.encrypt(
            _nonce(self._prefix, self._frame_index),
            plaintext,
            _aad(self._header_digest, self._frame_index, final),
        )
        self._output.write(struct.pack(">I", len(encrypted)))
        self._output.write(encrypted)
        self._frame_index += 1


class _HashingReader:
    def __init__(self, source: BinaryIO):
        self._source = source
        self.digest = hashlib.sha256()
        self.bytes_read = 0

    def read(self, size: int = -1) -> bytes:
        data = self._source.read(size)
        self.digest.update(data)
        self.bytes_read += len(data)
        return data


def _tar_info(name: str, size: int) -> tarfile.TarInfo:
    info = tarfile.TarInfo(name)
    info.size = size
    info.mode = 0o600
    info.mtime = 0
    info.uid = 0
    info.gid = 0
    info.uname = ""
    info.gname = ""
    return info


def _canonical_sources(
    manifest: BundleManifest,
    sources: Iterable[BundleMemberSource],
) -> tuple[BundleMemberSource, ...]:
    expected = [
        (role.role, member.path, member.bytes, member.sha256)
        for role in manifest.roles
        for member in role.members
    ]
    supplied = tuple(sources)
    actual = [(item.role, item.path, item.bytes, item.sha256) for item in supplied]
    if actual != expected:
        raise ValueError("member sources must exactly match the manifest order")
    return supplied


def write_bundle(
    output: BinaryIO,
    header: BundleHeader,
    manifest: BundleManifest,
    sources: Iterable[BundleMemberSource],
    password: str,
) -> None:
    """Write one complete bundle without seeking or materializing member content."""
    header_bytes = canonical_json_bytes(header)
    if not 0 < len(header_bytes) <= MAX_HEADER_BYTES:
        raise ValueError("header exceeds the container bound")
    canonical_sources = _canonical_sources(manifest, sources)
    manifest_bytes = _manifest_json_bytes(manifest)
    if len(manifest_bytes) > MAX_MANIFEST_BYTES:
        raise ValueError("manifest exceeds the format bound")
    output.write(MAGIC)
    output.write(struct.pack(">I", CONTAINER_VERSION))
    output.write(struct.pack(">I", len(header_bytes)))
    output.write(header_bytes)

    encrypted = _FrameEncryptingWriter(output, _derive_key(password, header), header, header_bytes)
    with tarfile.open(
        fileobj=encrypted,
        mode="w|",
        format=tarfile.PAX_FORMAT,
    ) as archive:
        archive.addfile(
            _tar_info(_MANIFEST_NAME, len(manifest_bytes)),
            io.BytesIO(manifest_bytes),
        )
        for source in canonical_sources:
            name = f"{_ROLE_PREFIX}/{source.role}/{source.path}"
            validate_tar_member_name(name)
            with source.opener() as stream:
                hashing = _HashingReader(stream)
                archive.addfile(_tar_info(name, source.bytes), hashing)
                if hashing.bytes_read != source.bytes:
                    raise ValueError("member source size changed while writing")
                if hashing.digest.hexdigest() != source.sha256:
                    raise ValueError("member source digest changed while writing")
                if stream.read(1):
                    raise ValueError("member source contains undeclared trailing bytes")
    encrypted.finalize()


def _read_exact(stream: BinaryIO, size: int) -> bytes:
    chunks = bytearray()
    while len(chunks) < size:
        part = stream.read(size - len(chunks))
        if not part:
            break
        chunks.extend(part)
    return bytes(chunks)


def _header_error(exc: ValidationError) -> BundleFormatError:
    for error in exc.errors():
        location = tuple(error.get("loc", ()))
        message = str(error.get("msg", ""))
        bounded_kdf_parameter = location == ("kdf",) and any(
            name in message for name in ("memory_cost", "iterations", "lanes")
        )
        if location[:1] == ("kdf",) and location[1:2] in {
            ("memory_cost",),
            ("iterations",),
            ("lanes",),
        } or bounded_kdf_parameter:
            return BundleFormatError("kdf_parameters_rejected", "validate_header")
        if location[:2] == ("kdf", "salt") and "exactly" in message:
            return BundleFormatError("kdf_parameters_rejected", "validate_header")
    return BundleFormatError("header_field_rejected", "validate_header")


def read_header(stream: BinaryIO) -> tuple[BundleHeader, bytes]:
    """Read and strictly validate only the clear container header."""
    prefix = _read_exact(stream, _CONTAINER_PREFIX_BYTES)
    if len(prefix) != _CONTAINER_PREFIX_BYTES or prefix[: len(MAGIC)] != MAGIC:
        raise BundleFormatError("malformed_container", "read_header")
    prefix_version = struct.unpack(">I", prefix[len(MAGIC) :])[0]
    if prefix_version != CONTAINER_VERSION:
        raise BundleFormatError("unsupported_container_version", "validate_header")
    encoded_length = _read_exact(stream, _LENGTH_BYTES)
    if len(encoded_length) != _LENGTH_BYTES:
        raise BundleFormatError("malformed_container", "read_header")
    header_length = struct.unpack(">I", encoded_length)[0]
    if not 0 < header_length <= MAX_HEADER_BYTES:
        raise BundleFormatError("malformed_container", "read_header")
    header_bytes = _read_exact(stream, header_length)
    if len(header_bytes) != header_length:
        raise BundleFormatError("malformed_container", "read_header")
    try:
        raw = json.loads(header_bytes.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise BundleFormatError("malformed_container", "read_header") from exc
    if isinstance(raw, dict) and raw.get("container_version") != CONTAINER_VERSION:
        raise BundleFormatError("unsupported_container_version", "validate_header")
    try:
        header = BundleHeader.model_validate(raw)
    except ValidationError as exc:
        raise _header_error(exc) from exc
    if canonical_json_bytes(header) != header_bytes:
        raise BundleFormatError("header_field_rejected", "validate_header")
    return header, header_bytes


class _FrameDecryptingReader(io.RawIOBase):
    def __init__(self, stream: BinaryIO, key: bytes, header: BundleHeader, header_bytes: bytes):
        self._stream = stream
        self._aead = AESGCM(key)
        self._prefix = decode_canonical_base64(
            header.cipher.nonce_prefix,
            NONCE_PREFIX_BYTES,
        )
        self._header_digest = hashlib.sha256(header_bytes).digest()
        self._lookahead = b""
        self._plaintext = memoryview(b"")
        self._frame_index = 0
        self._saw_frame = False
        self._physical_eof = False

    def readable(self) -> bool:
        return True

    def readinto(self, buffer: bytearray | memoryview) -> int:  # type: ignore[override]
        target = memoryview(buffer).cast("B")
        if len(self._plaintext) == 0 and not self._physical_eof:
            self._load_frame()
        if len(self._plaintext) == 0:
            return 0
        count = min(len(target), len(self._plaintext))
        target[:count] = self._plaintext[:count]
        self._plaintext = self._plaintext[count:]
        return count

    def drain(self) -> None:
        """Authenticate every remaining frame before a payload verdict is emitted."""
        sink = bytearray(_STREAM_BLOCK_BYTES)
        while self.readinto(sink):
            pass

    def _frame_length(self) -> int | None:
        first = self._lookahead
        self._lookahead = b""
        encoded = first + _read_exact(self._stream, _LENGTH_BYTES - len(first))
        if not encoded:
            return None
        if len(encoded) != _LENGTH_BYTES:
            raise BundleFormatError("malformed_container", "read_frames")
        length = cast(int, struct.unpack(">I", encoded)[0])
        if not _GCM_TAG_BYTES < length <= MAX_ENCRYPTED_FRAME_BYTES:
            raise BundleFormatError("malformed_container", "read_frames")
        return length

    def _load_frame(self) -> None:
        length = self._frame_length()
        if length is None:
            if not self._saw_frame:
                raise BundleFormatError("malformed_container", "read_frames")
            self._physical_eof = True
            return
        self._saw_frame = True
        encrypted = _read_exact(self._stream, length)
        if len(encrypted) != length:
            raise BundleFormatError("truncated_archive", "authenticate")
        self._lookahead = self._stream.read(1)
        physical_last = not self._lookahead
        if not physical_last and length != MAX_ENCRYPTED_FRAME_BYTES:
            raise BundleFormatError("malformed_container", "read_frames")
        nonce = _nonce(self._prefix, self._frame_index)
        try:
            plaintext = self._aead.decrypt(
                nonce,
                encrypted,
                _aad(self._header_digest, self._frame_index, physical_last),
            )
        except InvalidTag as exc:
            alternate_final = not physical_last
            try:
                self._aead.decrypt(
                    nonce,
                    encrypted,
                    _aad(self._header_digest, self._frame_index, alternate_final),
                )
            except InvalidTag:
                raise BundleFormatError("authentication_failed", "authenticate") from exc
            if physical_last:
                raise BundleFormatError("truncated_archive", "authenticate") from exc
            raise BundleFormatError("malformed_container", "read_frames") from exc
        self._plaintext = memoryview(plaintext)
        self._frame_index += 1
        if physical_last:
            self._physical_eof = True


def validate_tar_member_name(name: str) -> tuple[BundleRole, str]:
    """Validate and split one canonical regular role-member tar path."""
    if not name or "\\" in name or ":" in name or "\x00" in name:
        raise BundleFormatError("member_rejected", "validate_member")
    path = name.split("/")
    if len(path) < 3 or path[0] != _ROLE_PREFIX or any(part in {"", ".", ".."} for part in path):
        raise BundleFormatError("member_rejected", "validate_member")
    role_name = path[1]
    if role_name not in ROLE_ORDER:
        raise BundleFormatError("member_rejected", "validate_member")
    relative = "/".join(path[2:])
    try:
        validated = BundleMember(path=relative, bytes=0, sha256="0" * 64)
    except ValidationError as exc:
        raise BundleFormatError("member_rejected", "validate_member") from exc
    return cast(BundleRole, role_name), validated.path


def _manifest_from_member(archive: tarfile.TarFile, member: tarfile.TarInfo) -> BundleManifest:
    if member.name != _MANIFEST_NAME or not member.isfile():
        raise BundleFormatError("malformed_manifest", "read_manifest")
    extracted = archive.extractfile(member)
    if extracted is None:
        raise BundleFormatError("malformed_manifest", "read_manifest")
    content = bytearray()
    while True:
        chunk = extracted.read(_STREAM_BLOCK_BYTES)
        if not chunk:
            break
        if len(content) + len(chunk) > MAX_MANIFEST_BYTES:
            raise BundleFormatError("malformed_manifest", "read_manifest")
        content.extend(chunk)
    try:
        raw = json.loads(bytes(content).decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise BundleFormatError("malformed_manifest", "read_manifest") from exc
    if not isinstance(raw, dict):
        raise BundleFormatError("malformed_manifest", "validate_manifest")
    source_paths = raw.get("source_paths")
    if not isinstance(source_paths, dict) or tuple(source_paths) != ROLE_ORDER:
        raise BundleFormatError("malformed_manifest", "validate_manifest")
    contract_version = raw.get("bundle_contract_version")
    if type(contract_version) is int and contract_version != BUNDLE_CONTRACT_VERSION:
        compatible_shape = dict(raw)
        compatible_shape["bundle_contract_version"] = BUNDLE_CONTRACT_VERSION
        try:
            BundleManifest.model_validate(compatible_shape)
        except ValidationError as exc:
            raise BundleFormatError("malformed_manifest", "validate_manifest") from exc
        raise BundleFormatError("unsupported_contract_version", "validate_manifest")
    try:
        return cast(BundleManifest, BundleManifest.model_validate(raw))
    except ValidationError as exc:
        raise BundleFormatError("malformed_manifest", "validate_manifest") from exc


def _header_matches_manifest(header: BundleHeader, manifest: BundleManifest) -> bool:
    manifest_summary = tuple(
        (role.role, role.present, role.bytes) for role in manifest.roles
    )
    header_summary = tuple(
        (role.role, role.present, role.bytes) for role in header.roles_summary
    )
    return (
        header.created_at == manifest.created_at
        and header.cortex_version == manifest.cortex_version
        and header.contracts == manifest.contracts
        and header.embedding_fingerprint == manifest.embedding_fingerprint
        and header_summary == manifest_summary
    )


_PAYLOAD_PRIORITY: dict[BundleErrorCode, int] = {
    "malformed_payload": 0,
    "malformed_manifest": 1,
    "unsupported_contract_version": 2,
    "header_manifest_mismatch": 3,
    "member_rejected": 4,
    "member_digest_mismatch": 5,
}


def _prefer_payload_error(
    current: BundleFormatError | None,
    candidate: BundleFormatError,
) -> BundleFormatError:
    if current is None:
        return candidate
    current_priority = _PAYLOAD_PRIORITY.get(current.code, len(_PAYLOAD_PRIORITY))
    candidate_priority = _PAYLOAD_PRIORITY.get(candidate.code, len(_PAYLOAD_PRIORITY))
    return candidate if candidate_priority < current_priority else current


def _expected_members(manifest: BundleManifest) -> tuple[tuple[BundleRole, BundleMember], ...]:
    return tuple(
        (role.role, member)
        for role in manifest.roles
        for member in role.members
    )


def _validate_manifest_digests(manifest: BundleManifest) -> BundleFormatError | None:
    for role in manifest.roles:
        if role.present and compute_members_digest(role.members) != role.members_digest:
            return BundleFormatError("member_digest_mismatch", "validate_member")
    return None


def _consume_payload(
    reader: _FrameDecryptingReader,
    header: BundleHeader,
    fastembed_version: str,
) -> BundleVerification:
    payload_error: BundleFormatError | None = None
    manifest: BundleManifest | None = None
    expected: tuple[tuple[BundleRole, BundleMember], ...] = ()
    member_index = 0
    seen_names: set[str] = set()
    payload_exception: BaseException | None = None
    try:
        with tarfile.open(fileobj=reader, mode="r|", format=tarfile.PAX_FORMAT) as archive:
            iterator = iter(archive)
            try:
                first = next(iterator)
            except StopIteration:
                payload_error = BundleFormatError("malformed_manifest", "read_manifest")
            else:
                try:
                    manifest = _manifest_from_member(archive, first)
                except BundleFormatError as exc:
                    payload_error = _prefer_payload_error(payload_error, exc)
                if manifest is not None:
                    expected = _expected_members(manifest)
                    digest_error = _validate_manifest_digests(manifest)
                    if digest_error is not None:
                        payload_error = _prefer_payload_error(payload_error, digest_error)
                    if not _header_matches_manifest(header, manifest):
                        payload_error = _prefer_payload_error(
                            payload_error,
                            BundleFormatError(
                                "header_manifest_mismatch",
                                "compare_header",
                                header_matches_manifest=False,
                            ),
                        )
            for member in iterator:
                actual_digest = hashlib.sha256()
                actual_bytes = 0
                regular_file = member.isfile()
                try:
                    if not regular_file or member.name in seen_names:
                        raise BundleFormatError("member_rejected", "validate_member")
                    seen_names.add(member.name)
                    role, relative = validate_tar_member_name(member.name)
                    if member_index >= len(expected):
                        raise BundleFormatError("member_rejected", "validate_member")
                    expected_role, expected_member = expected[member_index]
                    if role != expected_role or relative != expected_member.path:
                        raise BundleFormatError("member_rejected", "validate_member")
                except BundleFormatError as exc:
                    payload_error = _prefer_payload_error(payload_error, exc)
                    expected_member = None
                extracted = archive.extractfile(member) if regular_file else None
                if extracted is None:
                    payload_error = _prefer_payload_error(
                        payload_error,
                        BundleFormatError("member_rejected", "validate_member"),
                    )
                else:
                    while True:
                        chunk = extracted.read(_STREAM_BLOCK_BYTES)
                        if not chunk:
                            break
                        actual_digest.update(chunk)
                        actual_bytes += len(chunk)
                if expected_member is not None and (
                    actual_bytes != expected_member.bytes
                    or actual_digest.hexdigest() != expected_member.sha256
                ):
                    payload_error = _prefer_payload_error(
                        payload_error,
                        BundleFormatError("member_digest_mismatch", "validate_member"),
                    )
                member_index += 1
    except BundleFormatError:
        raise
    except (tarfile.TarError, OSError, EOFError) as exc:
        payload_error = _prefer_payload_error(
            payload_error,
            BundleFormatError("malformed_payload", "read_payload"),
        )
        payload_exception = exc
    reader.drain()
    if manifest is not None and member_index != len(expected):
        payload_error = _prefer_payload_error(
            payload_error,
            BundleFormatError("member_rejected", "validate_member"),
        )
    if payload_error is not None:
        if payload_exception is not None:
            raise payload_error from payload_exception
        raise payload_error
    if manifest is None:
        raise BundleFormatError("malformed_manifest", "read_manifest")
    return BundleVerification(
        header=header,
        manifest=manifest,
        compatible=is_compatible(
            manifest.contracts,
            manifest.embedding_fingerprint,
            fastembed_version,
        ),
    )


def verify_bundle(
    stream: BinaryIO,
    password: str,
    fastembed_version: str,
) -> BundleVerification:
    """Authenticate and verify one entire bundle without extracting any member."""
    header, header_bytes = read_header(stream)
    reader = _FrameDecryptingReader(
        stream,
        _derive_key(password, header),
        header,
        header_bytes,
    )
    return _consume_payload(reader, header, fastembed_version)


__all__ = [
    "MAGIC",
    "BundleFormatError",
    "BundleMemberSource",
    "BundleVerification",
    "build_local_fingerprint",
    "canonical_json_bytes",
    "compute_members_digest",
    "is_compatible",
    "read_header",
    "validate_tar_member_name",
    "verify_bundle",
    "write_bundle",
]
