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
"""Adversarial and streaming tests for the versioned bundle format."""

from __future__ import annotations

import base64
import hashlib
import io
import json
import struct
import tarfile
import tracemalloc
from collections.abc import Callable
from pathlib import Path

import pytest
from cryptography.hazmat.primitives.ciphers.aead import AESGCM

from bundle_contract import (
    EXCLUDED_ITEMS,
    MAX_MANIFEST_BYTES,
    NONCE_PREFIX_BYTES,
    ROLE_ORDER,
    BundleHeader,
    BundleManifest,
    BundleMember,
    BundleRoleManifest,
    CipherParameters,
    ExcludedItem,
    KdfParameters,
    RoleSummary,
    SourcePaths,
    decode_canonical_base64,
    local_index_contracts,
)
from bundle_format import (
    MAGIC,
    BundleFormatError,
    BundleMemberSource,
    _aad,
    _derive_key,
    _FrameEncryptingWriter,
    _manifest_json_bytes,
    _nonce,
    build_local_fingerprint,
    canonical_json_bytes,
    compute_members_digest,
    read_header,
    verify_bundle,
    write_bundle,
)

_PASSWORD = "correct horse battery staple"
_FASTEMBED_VERSION = "0.8.0"
_CREATED_AT = "2026-08-07T20:00:00Z"
_CORTEX_VERSION = "2026.0805.00"


class ZeroStream(io.RawIOBase):
    """Generate a fixed number of zero bytes without materializing them."""

    def __init__(self, size: int):
        self._remaining = size

    def readable(self) -> bool:
        return True

    def read(self, size: int = -1) -> bytes:
        if self._remaining == 0:
            return b""
        count = self._remaining if size < 0 else min(size, self._remaining)
        self._remaining -= count
        return b"\x00" * count


def _zero_digest(size: int) -> str:
    digest = hashlib.sha256()
    block = b"\x00" * (1024 * 1024)
    remaining = size
    while remaining:
        count = min(len(block), remaining)
        digest.update(block[:count])
        remaining -= count
    return digest.hexdigest()


def _components(
    payloads: dict[str, tuple[tuple[str, bytes], ...]],
) -> tuple[BundleHeader, BundleManifest, tuple[BundleMemberSource, ...]]:
    roles: list[BundleRoleManifest] = []
    sources: list[BundleMemberSource] = []
    source_paths: dict[str, str | None] = {role: None for role in ROLE_ORDER}
    for role in ROLE_ORDER:
        declared: list[BundleMember] = []
        for path, content in sorted(
            payloads.get(role, ()),
            key=lambda item: item[0].encode("utf-8"),
        ):
            digest = hashlib.sha256(content).hexdigest()
            member = BundleMember(path=path, bytes=len(content), sha256=digest)
            declared.append(member)
            sources.append(
                BundleMemberSource(
                    role=role,
                    path=path,
                    bytes=len(content),
                    sha256=digest,
                    opener=lambda content=content: io.BytesIO(content),
                )
            )
        if declared:
            source_paths[role] = f"C:/source/{role}"
            roles.append(
                BundleRoleManifest(
                    role=role,
                    present=True,
                    reason_absent=None,
                    members=tuple(declared),
                    bytes=sum(item.bytes for item in declared),
                    members_digest=compute_members_digest(declared),
                )
            )
        else:
            roles.append(
                BundleRoleManifest(
                    role=role,
                    present=False,
                    reason_absent="file_not_found",
                    members=(),
                    bytes=0,
                    members_digest=None,
                )
            )
    contracts = local_index_contracts()
    fingerprint = build_local_fingerprint(_FASTEMBED_VERSION)
    manifest = BundleManifest(
        bundle_contract_version=1,
        created_at=_CREATED_AT,
        cortex_version=_CORTEX_VERSION,
        contracts=contracts,
        embedding_fingerprint=fingerprint,
        source_paths=SourcePaths(**source_paths),
        roles=tuple(roles),
        excluded=tuple(ExcludedItem(item=item, reason=reason) for item, reason in EXCLUDED_ITEMS),
    )
    header = BundleHeader(
        container_version=1,
        format="cortexbundle",
        created_at=_CREATED_AT,
        cortex_version=_CORTEX_VERSION,
        compression="none",
        contracts=contracts,
        embedding_fingerprint=fingerprint,
        roles_summary=tuple(
            RoleSummary(role=role.role, present=role.present, bytes=role.bytes)
            for role in roles
        ),
        kdf=KdfParameters(
            name="argon2id",
            salt=base64.b64encode(b"s" * 16).decode("ascii"),
            memory_cost=8192,
            iterations=1,
            lanes=1,
        ),
        cipher=CipherParameters(
            name="aes-256-gcm",
            frame_bytes=1048576,
            nonce_prefix=base64.b64encode(b"n" * 4).decode("ascii"),
        ),
    )
    return header, manifest, tuple(sources)


def _archive(
    payloads: dict[str, tuple[tuple[str, bytes], ...]] | None = None,
    *,
    header_transform: Callable[[BundleHeader], BundleHeader] | None = None,
) -> tuple[bytes, BundleHeader, BundleManifest]:
    header, manifest, sources = _components(
        {"config": (("config.toml", b"schema_version = 1\n"),)}
        if payloads is None
        else payloads
    )
    if header_transform is not None:
        header = header_transform(header)
    output = io.BytesIO()
    write_bundle(output, header, manifest, sources, _PASSWORD)
    return output.getvalue(), header, manifest


def _tar_info(name: str, size: int, type_: bytes = tarfile.REGTYPE) -> tarfile.TarInfo:
    info = tarfile.TarInfo(name)
    info.size = size
    info.type = type_
    info.mtime = 0
    return info


def _raw_tar(
    manifest_bytes: bytes,
    entries: tuple[tuple[str, bytes, bytes], ...] = (),
) -> bytes:
    output = io.BytesIO()
    with tarfile.open(fileobj=output, mode="w", format=tarfile.PAX_FORMAT) as archive:
        archive.addfile(
            _tar_info("manifest.json", len(manifest_bytes)),
            io.BytesIO(manifest_bytes),
        )
        for name, content, type_ in entries:
            info = _tar_info(name, len(content) if type_ == tarfile.REGTYPE else 0, type_)
            archive.addfile(info, io.BytesIO(content) if type_ == tarfile.REGTYPE else None)
    return output.getvalue()


def _encrypt_payload(header: BundleHeader, payload: bytes) -> bytes:
    header_bytes = canonical_json_bytes(header)
    output = io.BytesIO()
    output.write(MAGIC)
    output.write(struct.pack(">I", 1))
    output.write(struct.pack(">I", len(header_bytes)))
    output.write(header_bytes)
    writer = _FrameEncryptingWriter(
        output,
        _derive_key(_PASSWORD, header),
        header,
        header_bytes,
    )
    writer.write(payload)
    writer.finalize()
    return output.getvalue()


def _encrypt_payload_chunks(header: BundleHeader, chunks: tuple[bytes, ...]) -> bytes:
    header_bytes = canonical_json_bytes(header)
    header_digest = hashlib.sha256(header_bytes).digest()
    nonce_prefix = decode_canonical_base64(
        header.cipher.nonce_prefix,
        NONCE_PREFIX_BYTES,
    )
    cipher = AESGCM(_derive_key(_PASSWORD, header))
    output = io.BytesIO()
    output.write(MAGIC)
    output.write(struct.pack(">I", 1))
    output.write(struct.pack(">I", len(header_bytes)))
    output.write(header_bytes)
    for index, chunk in enumerate(chunks):
        final = index == len(chunks) - 1
        encrypted = cipher.encrypt(
            _nonce(nonce_prefix, index),
            chunk,
            _aad(header_digest, index, final),
        )
        output.write(struct.pack(">I", len(encrypted)))
        output.write(encrypted)
    return output.getvalue()


def _raw_manifest_archive(
    header: BundleHeader,
    manifest_payload: dict[str, object] | bytes,
    entries: tuple[tuple[str, bytes, bytes], ...] = (),
) -> bytes:
    encoded = (
        manifest_payload
        if isinstance(manifest_payload, bytes)
        else json.dumps(manifest_payload, sort_keys=False, separators=(",", ":")).encode()
    )
    return _encrypt_payload(header, _raw_tar(encoded, entries))


def _frame_chunks(archive: bytes) -> tuple[bytes, list[bytes]]:
    header_length = struct.unpack(">I", archive[16:20])[0]
    offset = 20 + header_length
    prefix = archive[:offset]
    chunks: list[bytes] = []
    while offset < len(archive):
        length = struct.unpack(">I", archive[offset : offset + 4])[0]
        end = offset + 4 + length
        chunks.append(archive[offset:end])
        offset = end
    return prefix, chunks


def _raw_header_container(
    payload: dict[str, object],
    *,
    prefix_version: int = 1,
) -> bytes:
    encoded = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()
    return MAGIC + struct.pack(">I", prefix_version) + struct.pack(">I", len(encoded)) + encoded


def test_round_trip_verifies_members_and_manifest() -> None:
    archive, _, manifest = _archive(
        {
            "chroma": (("alpha.bin", b"alpha"), ("nested/beta.bin", b"beta")),
            "config": (("config.toml", b"schema_version = 1\n"),),
        }
    )
    result = verify_bundle(io.BytesIO(archive), _PASSWORD, _FASTEMBED_VERSION)
    assert result.compatible is True
    assert result.manifest == manifest
    assert tuple(role.role for role in result.manifest.roles) == ROLE_ORDER


def test_manifest_source_paths_preserve_canonical_role_order() -> None:
    header, manifest, _ = _components({})
    encoded = _manifest_json_bytes(manifest)
    raw = json.loads(encoded)
    assert tuple(raw["source_paths"]) == ROLE_ORDER

    raw["source_paths"] = dict(sorted(raw["source_paths"].items()))
    archive = _raw_manifest_archive(header, raw)
    with pytest.raises(BundleFormatError, match="malformed_manifest"):
        verify_bundle(io.BytesIO(archive), _PASSWORD, _FASTEMBED_VERSION)


def test_members_digest_matches_an_independent_implementation() -> None:
    members = (
        BundleMember(path="a", bytes=1, sha256="1" * 64),
        BundleMember(path="b", bytes=2, sha256="2" * 64),
    )
    independent = hashlib.sha256(
        json.dumps(
            [item.model_dump(mode="json") for item in members],
            sort_keys=True,
            separators=(",", ":"),
            ensure_ascii=False,
        ).encode("utf-8")
    ).hexdigest()
    assert compute_members_digest(members) == independent


@pytest.mark.parametrize(
    "field",
    ["created_at", "cortex_version", "contracts", "embedding_fingerprint", "roles_summary"],
)
def test_each_header_manifest_family_mismatch_is_rejected(field: str) -> None:
    def contradict(header: BundleHeader) -> BundleHeader:
        if field == "created_at":
            return header.model_copy(update={field: "2026-08-08T20:00:00Z"})
        if field == "cortex_version":
            return header.model_copy(update={field: "different"})
        if field == "contracts":
            changed = header.contracts.model_copy(
                update={"metadata_schema_version": header.contracts.metadata_schema_version + 1}
            )
            return header.model_copy(update={field: changed})
        if field == "embedding_fingerprint":
            changed = header.embedding_fingerprint.model_copy(
                update={"fastembed_version": "different"}
            )
            return header.model_copy(update={field: changed})
        summaries = list(header.roles_summary)
        summaries[0] = summaries[0].model_copy(update={"present": True})
        return header.model_copy(update={field: tuple(summaries)})

    archive, _, _ = _archive(header_transform=contradict)
    with pytest.raises(BundleFormatError) as caught:
        verify_bundle(io.BytesIO(archive), _PASSWORD, _FASTEMBED_VERSION)
    assert caught.value.code == "header_manifest_mismatch"
    assert caught.value.header_matches_manifest is False


def test_wrong_password_and_altered_frame_share_authentication_failure() -> None:
    archive, _, _ = _archive()
    with pytest.raises(BundleFormatError, match="authentication_failed"):
        verify_bundle(io.BytesIO(archive), "wrong", _FASTEMBED_VERSION)
    altered = bytearray(archive)
    altered[-1] ^= 1
    with pytest.raises(BundleFormatError, match="authentication_failed"):
        verify_bundle(io.BytesIO(altered), _PASSWORD, _FASTEMBED_VERSION)


def test_truncated_archive_is_distinguished_from_authentication_failure() -> None:
    archive, _, _ = _archive({"chroma": (("large.bin", b"x" * (2 * 1024 * 1024)),)})
    prefix, frames = _frame_chunks(archive)
    assert len(frames) >= 2
    truncated = prefix + frames[0]
    with pytest.raises(BundleFormatError, match="truncated_archive"):
        verify_bundle(io.BytesIO(truncated), _PASSWORD, _FASTEMBED_VERSION)


@pytest.mark.parametrize("mutation", ["permuted", "replayed"])
def test_frame_permutation_and_replay_are_rejected(mutation: str) -> None:
    archive, _, _ = _archive({"chroma": (("large.bin", b"x" * (3 * 1024 * 1024)),)})
    prefix, frames = _frame_chunks(archive)
    assert len(frames) >= 3
    changed = (
        [frames[1], frames[0], *frames[2:]]
        if mutation == "permuted"
        else [frames[0], frames[0], *frames[1:]]
    )
    with pytest.raises(BundleFormatError, match="authentication_failed"):
        verify_bundle(io.BytesIO(prefix + b"".join(changed)), _PASSWORD, _FASTEMBED_VERSION)


def _noncanonical_base64(value: str) -> str:
    alphabet = "ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789+/"
    index = alphabet.index(value[-3])
    return value[:-3] + alphabet[index ^ 1] + value[-2:]


@pytest.mark.parametrize(
    ("case", "expected"),
    [
        ("format", "header_field_rejected"),
        ("container_version", "unsupported_container_version"),
        ("compression", "header_field_rejected"),
        ("cipher_name", "header_field_rejected"),
        ("frame_bytes", "header_field_rejected"),
        ("kdf_name", "header_field_rejected"),
        ("urlsafe", "header_field_rejected"),
        ("no_padding", "header_field_rejected"),
        ("noncanonical", "header_field_rejected"),
        ("salt_length", "kdf_parameters_rejected"),
        ("nonce_length", "header_field_rejected"),
        ("contract_unknown", "header_field_rejected"),
        ("contract_missing", "header_field_rejected"),
        ("role_order", "header_field_rejected"),
    ],
)
def test_each_fixed_header_value_is_rejected(case: str, expected: str) -> None:
    header, _, _ = _components({"config": (("config.toml", b"x"),)})
    raw = header.model_dump(mode="json")
    prefix_version = 1
    if case == "format":
        raw["format"] = "other"
    elif case == "container_version":
        raw["container_version"] = 2
        prefix_version = 2
    elif case == "compression":
        raw["compression"] = "gzip"
    elif case == "cipher_name":
        raw["cipher"]["name"] = "other"
    elif case == "frame_bytes":
        raw["cipher"]["frame_bytes"] = 1
    elif case == "kdf_name":
        raw["kdf"]["name"] = "other"
    elif case == "urlsafe":
        raw["kdf"]["salt"] = "_" + raw["kdf"]["salt"][1:]
    elif case == "no_padding":
        raw["kdf"]["salt"] = raw["kdf"]["salt"].rstrip("=")
    elif case == "noncanonical":
        raw["kdf"]["salt"] = _noncanonical_base64(raw["kdf"]["salt"])
    elif case == "salt_length":
        raw["kdf"]["salt"] = base64.b64encode(b"s" * 17).decode()
    elif case == "nonce_length":
        raw["cipher"]["nonce_prefix"] = base64.b64encode(b"n" * 3).decode()
    elif case == "contract_unknown":
        raw["contracts"]["unknown"] = 1
    elif case == "contract_missing":
        del raw["contracts"]["embedding_pooling"]
    elif case == "role_order":
        raw["roles_summary"][0], raw["roles_summary"][1] = (
            raw["roles_summary"][1],
            raw["roles_summary"][0],
        )
    with pytest.raises(BundleFormatError) as caught:
        read_header(io.BytesIO(_raw_header_container(raw, prefix_version=prefix_version)))
    assert caught.value.code == expected


def test_noncanonical_clear_header_is_rejected() -> None:
    header, _, _ = _components({})
    encoded = json.dumps(header.model_dump(mode="json"), indent=2).encode()
    container = MAGIC + struct.pack(">I", 1) + struct.pack(">I", len(encoded)) + encoded
    with pytest.raises(BundleFormatError, match="header_field_rejected"):
        read_header(io.BytesIO(container))


def test_nonfinal_frame_must_have_the_declared_plaintext_size() -> None:
    header, manifest, _ = _components({})
    payload = _raw_tar(_manifest_json_bytes(manifest))
    archive = _encrypt_payload_chunks(header, (payload[:1], payload[1:]))
    with pytest.raises(BundleFormatError, match="malformed_container"):
        verify_bundle(io.BytesIO(archive), _PASSWORD, _FASTEMBED_VERSION)


def test_unsupported_manifest_contract_version_is_rejected() -> None:
    header, manifest, _ = _components({"config": (("config.toml", b"x"),)})
    raw = manifest.model_dump(mode="json")
    raw["bundle_contract_version"] = 2
    archive = _raw_manifest_archive(header, raw)
    with pytest.raises(BundleFormatError, match="unsupported_contract_version"):
        verify_bundle(io.BytesIO(archive), _PASSWORD, _FASTEMBED_VERSION)


@pytest.mark.parametrize(
    ("name", "type_", "duplicate"),
    [
        ("/absolute", tarfile.REGTYPE, False),
        ("roles/config/../escape", tarfile.REGTYPE, False),
        ("roles/config/C:drive", tarfile.REGTYPE, False),
        ("roles/config/link", tarfile.SYMTYPE, False),
        ("roles/config/config.toml", tarfile.REGTYPE, True),
        ("roles/unknown/file", tarfile.REGTYPE, False),
    ],
)
def test_each_hostile_member_form_is_rejected(name: str, type_: bytes, duplicate: bool) -> None:
    header, manifest, _ = _components({"config": (("config.toml", b"x"),)})
    entries = [(name, b"x", type_)]
    if duplicate:
        entries.append((name, b"x", type_))
    archive = _raw_manifest_archive(header, manifest.model_dump(mode="json"), tuple(entries))
    with pytest.raises(BundleFormatError, match="member_rejected"):
        verify_bundle(io.BytesIO(archive), _PASSWORD, _FASTEMBED_VERSION)


def test_noncanonical_tar_member_order_is_rejected() -> None:
    header, manifest, _ = _components(
        {"config": (("a.toml", b"a"), ("b.toml", b"b"))}
    )
    entries = (
        ("roles/config/b.toml", b"b", tarfile.REGTYPE),
        ("roles/config/a.toml", b"a", tarfile.REGTYPE),
    )
    archive = _raw_manifest_archive(header, manifest.model_dump(mode="json"), entries)
    with pytest.raises(BundleFormatError, match="member_rejected"):
        verify_bundle(io.BytesIO(archive), _PASSWORD, _FASTEMBED_VERSION)


@pytest.mark.parametrize("target", ["member", "aggregate"])
def test_member_and_aggregate_digest_mismatches_are_rejected(target: str) -> None:
    header, manifest, _ = _components({"config": (("config.toml", b"x"),)})
    raw = manifest.model_dump(mode="json")
    config_role = raw["roles"][3]
    if target == "member":
        config_role["members"][0]["sha256"] = "0" * 64
        config_role["members_digest"] = hashlib.sha256(
            json.dumps(
                config_role["members"],
                sort_keys=True,
                separators=(",", ":"),
            ).encode()
        ).hexdigest()
    else:
        config_role["members_digest"] = "0" * 64
    archive = _raw_manifest_archive(
        header,
        raw,
        (("roles/config/config.toml", b"x", tarfile.REGTYPE),),
    )
    with pytest.raises(BundleFormatError, match="member_digest_mismatch"):
        verify_bundle(io.BytesIO(archive), _PASSWORD, _FASTEMBED_VERSION)


def test_malformed_tar_and_manifest_are_distinct() -> None:
    header, _, _ = _components({"config": (("config.toml", b"x"),)})
    with pytest.raises(BundleFormatError, match="malformed_payload"):
        verify_bundle(
            io.BytesIO(_encrypt_payload(header, b"not a tar stream")),
            _PASSWORD,
            _FASTEMBED_VERSION,
        )
    malformed_manifest = _encrypt_payload(header, _raw_tar(b"not json"))
    with pytest.raises(BundleFormatError, match="malformed_manifest"):
        verify_bundle(io.BytesIO(malformed_manifest), _PASSWORD, _FASTEMBED_VERSION)


def test_truncation_precedes_an_invalid_manifest() -> None:
    header, _, _ = _components({"config": (("config.toml", b"x"),)})
    payload = _raw_tar(b"not json") + (b"x" * (2 * 1024 * 1024))
    archive = _encrypt_payload(header, payload)
    prefix, frames = _frame_chunks(archive)
    with pytest.raises(BundleFormatError, match="truncated_archive"):
        verify_bundle(io.BytesIO(prefix + frames[0]), _PASSWORD, _FASTEMBED_VERSION)


def test_verify_streams_more_than_64_mib_under_memory_ceiling() -> None:
    size = 65 * 1024 * 1024
    digest = _zero_digest(size)
    header, manifest, _ = _components({"chroma": (("large.bin", b"placeholder"),)})
    member = BundleMember(path="large.bin", bytes=size, sha256=digest)
    role = BundleRoleManifest(
        role="chroma",
        present=True,
        reason_absent=None,
        members=(member,),
        bytes=size,
        members_digest=compute_members_digest((member,)),
    )
    roles = (role, *manifest.roles[1:])
    manifest = manifest.model_copy(
        update={
            "roles": roles,
            "source_paths": manifest.source_paths.model_copy(
                update={"chroma": "C:/source/chroma"}
            ),
        }
    )
    summaries = (RoleSummary(role="chroma", present=True, bytes=size), *header.roles_summary[1:])
    header = header.model_copy(update={"roles_summary": summaries})
    source = BundleMemberSource(
        role="chroma",
        path="large.bin",
        bytes=size,
        sha256=digest,
        opener=lambda: ZeroStream(size),
    )
    output = io.BytesIO()
    write_bundle(output, header, manifest, (source,), _PASSWORD)
    output.seek(0)
    tracemalloc.start()
    verify_bundle(output, _PASSWORD, _FASTEMBED_VERSION)
    _, peak = tracemalloc.get_traced_memory()
    tracemalloc.stop()
    assert peak < 32 * 1024 * 1024


def _manifest_at_size(manifest: BundleManifest, size: int) -> bytes:
    raw = manifest.model_dump(mode="json")
    raw["roles"][0]["reason_absent"] = ""
    base = json.dumps(
        raw,
        ensure_ascii=False,
        sort_keys=False,
        separators=(",", ":"),
    ).encode()
    padding = size - len(base)
    assert padding >= 0
    raw["roles"][0]["reason_absent"] = "x" * padding
    encoded = json.dumps(
        raw,
        ensure_ascii=False,
        sort_keys=False,
        separators=(",", ":"),
    ).encode()
    assert len(encoded) == size
    return encoded


def test_manifest_at_bound_stays_under_its_memory_ceiling() -> None:
    header, manifest, _ = _components({})
    payload = _raw_tar(_manifest_at_size(manifest, MAX_MANIFEST_BYTES))
    archive = _encrypt_payload(header, payload)
    tracemalloc.start()
    result = verify_bundle(io.BytesIO(archive), _PASSWORD, _FASTEMBED_VERSION)
    _, peak = tracemalloc.get_traced_memory()
    tracemalloc.stop()
    assert result.manifest.roles[0].reason_absent
    assert peak < 96 * 1024 * 1024


def test_manifest_over_bound_stops_during_read_under_memory_ceiling() -> None:
    header, manifest, _ = _components({})
    payload = _raw_tar(_manifest_at_size(manifest, MAX_MANIFEST_BYTES + 1))
    archive = _encrypt_payload(header, payload)
    tracemalloc.start()
    with pytest.raises(BundleFormatError, match="malformed_manifest"):
        verify_bundle(io.BytesIO(archive), _PASSWORD, _FASTEMBED_VERSION)
    _, peak = tracemalloc.get_traced_memory()
    tracemalloc.stop()
    assert peak < 96 * 1024 * 1024


def test_member_path_never_uses_whole_file_convenience_methods() -> None:
    source = Path(__file__).resolve().parents[1] / "bundle_format.py"
    text = source.read_text(encoding="utf-8")
    assert ".read_bytes(" not in text
    assert ".read_text(" not in text
