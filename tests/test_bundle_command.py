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
"""Machine-contract tests for bundle describe and verify commands."""

from __future__ import annotations

import base64
import io
import json
import os
import struct
import subprocess
import sys
import time
from collections.abc import Callable
from pathlib import Path

import fastembed
import pytest

import bundle_command
from bundle_contract import (
    BUNDLE_COMPRESSION,
    BUNDLE_CONTRACT_VERSION,
    BUNDLE_FORMAT,
    CIPHER_NAME,
    CONTAINER_VERSION,
    EXCLUDED_ITEMS,
    FRAME_BYTES,
    KDF_NAME,
    ROLE_ORDER,
    BundleErrorCode,
    BundleHeader,
    BundleManifest,
    BundleRoleManifest,
    CipherParameters,
    EmbeddingFingerprint,
    ExcludedItem,
    IndexContracts,
    KdfParameters,
    RoleSummary,
    SourcePaths,
)
from bundle_format import BundleFormatError, write_bundle
from confluence_writer.constants import (
    EXIT_ERROR,
    EXIT_INTEGRITY,
    EXIT_INVALID_INPUT,
    EXIT_NOT_FOUND,
    EXIT_OK,
)
from index_contract import (
    CHUNKING_CONTRACT_VERSION,
    EMBEDDING_MODEL,
    EMBEDDING_POOLING,
    LEXICAL_INDEX_CONTRACT_VERSION,
    METADATA_SCHEMA_VERSION,
)

_ROOT = Path(__file__).resolve().parents[1]
_PASSWORD = "correct horse battery staple"
_COMMON_FIELDS = {
    "contract_version",
    "operation",
    "status",
    "error",
    "restart_required",
}
_ERROR_EXITS: tuple[tuple[BundleErrorCode, int], ...] = (
    ("archive_not_found", EXIT_NOT_FOUND),
    ("archive_unreadable", EXIT_ERROR),
    ("malformed_container", EXIT_INVALID_INPUT),
    ("unsupported_container_version", EXIT_INVALID_INPUT),
    ("header_field_rejected", EXIT_INVALID_INPUT),
    ("kdf_parameters_rejected", EXIT_INVALID_INPUT),
    ("password_missing", EXIT_INVALID_INPUT),
    ("kdf_unavailable", EXIT_ERROR),
    ("authentication_failed", EXIT_INTEGRITY),
    ("truncated_archive", EXIT_INTEGRITY),
    ("malformed_payload", EXIT_INTEGRITY),
    ("malformed_manifest", EXIT_INTEGRITY),
    ("unsupported_contract_version", EXIT_INTEGRITY),
    ("header_manifest_mismatch", EXIT_INTEGRITY),
    ("member_rejected", EXIT_INTEGRITY),
    ("member_digest_mismatch", EXIT_INTEGRITY),
)


def _contracts() -> IndexContracts:
    return IndexContracts(
        metadata_schema_version=METADATA_SCHEMA_VERSION,
        chunking_contract_version=CHUNKING_CONTRACT_VERSION,
        lexical_index_contract_version=LEXICAL_INDEX_CONTRACT_VERSION,
        embedding_model=EMBEDDING_MODEL,
        embedding_pooling=EMBEDDING_POOLING,
    )


def _fingerprint() -> EmbeddingFingerprint:
    return EmbeddingFingerprint(
        embedding_model=EMBEDDING_MODEL,
        fastembed_version=fastembed.__version__,
        pooling=EMBEDDING_POOLING,
    )


def _write_valid_archive(path: Path) -> None:
    roles = tuple(
        BundleRoleManifest(
            role=role,
            present=False,
            reason_absent="not present in this fixture",
            members=(),
            bytes=0,
            members_digest=None,
        )
        for role in ROLE_ORDER
    )
    contracts = _contracts()
    fingerprint = _fingerprint()
    created_at = "2026-08-07T20:00:00Z"
    header = BundleHeader(
        container_version=CONTAINER_VERSION,
        format=BUNDLE_FORMAT,
        created_at=created_at,
        cortex_version="2026.805.0",
        compression=BUNDLE_COMPRESSION,
        contracts=contracts,
        embedding_fingerprint=fingerprint,
        roles_summary=tuple(
            RoleSummary(role=role, present=False, bytes=0) for role in ROLE_ORDER
        ),
        kdf=KdfParameters(
            name=KDF_NAME,
            salt=base64.b64encode(b"s" * 16).decode("ascii"),
            memory_cost=8192,
            iterations=1,
            lanes=1,
        ),
        cipher=CipherParameters(
            name=CIPHER_NAME,
            frame_bytes=FRAME_BYTES,
            nonce_prefix=base64.b64encode(b"n" * 4).decode("ascii"),
        ),
    )
    manifest = BundleManifest(
        bundle_contract_version=BUNDLE_CONTRACT_VERSION,
        created_at=created_at,
        cortex_version="2026.805.0",
        contracts=contracts,
        embedding_fingerprint=fingerprint,
        source_paths=SourcePaths(
            chroma=None,
            lexical=None,
            ingestion_store=None,
            config=None,
            ingestion_config=None,
            confluence_config=None,
        ),
        roles=roles,
        excluded=tuple(
            ExcludedItem(item=item, reason=reason) for item, reason in EXCLUDED_ITEMS
        ),
    )
    with path.open("wb") as stream:
        write_bundle(stream, header, manifest, (), _PASSWORD)


def _payload(output: io.StringIO) -> dict[str, object]:
    return json.loads(output.getvalue())


def _rewrite_clear_header(
    path: Path,
    transform: Callable[[dict[str, object]], None],
) -> None:
    with path.open("rb") as stream:
        archive = stream.read()
    header_length = struct.unpack(">I", archive[16:20])[0]
    header = json.loads(archive[20 : 20 + header_length].decode("utf-8"))
    transform(header)
    encoded = json.dumps(
        header,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    changed = archive[:16] + struct.pack(">I", len(encoded)) + encoded
    changed += archive[20 + header_length :]
    with path.open("wb") as stream:
        stream.write(changed)


def test_describe_and_verify_success_return_complete_envelopes(tmp_path: Path) -> None:
    archive = tmp_path / "valid.cortexbundle"
    _write_valid_archive(archive)

    describe_output = io.StringIO()
    assert bundle_command.main(
        ["describe", str(archive), "--json"], output=describe_output
    ) == EXIT_OK
    describe = _payload(describe_output)
    assert list(describe) == [
        "contract_version",
        "operation",
        "status",
        "error",
        "restart_required",
        "authenticated",
        "claimed_compatible",
        "created_at",
        "cortex_version",
        "roles_summary",
    ]
    assert describe["operation"] == "bundle_describe"
    assert describe["status"] == "succeeded"
    assert describe["error"] is None
    assert describe["authenticated"] is False

    verify_output = io.StringIO()
    assert bundle_command.main(
        ["verify", str(archive), "--json", "--password-stdin"],
        input_stream=io.StringIO(_PASSWORD + "\n"),
        output=verify_output,
    ) == EXIT_OK
    verify = _payload(verify_output)
    assert list(verify) == [
        "contract_version",
        "operation",
        "status",
        "error",
        "restart_required",
        "authenticated",
        "compatible",
        "header_matches_manifest",
        "members_verified",
        "roles",
    ]
    assert verify["operation"] == "bundle_verify"
    assert verify["status"] == "succeeded"
    assert verify["error"] is None
    assert verify["authenticated"] is True
    assert verify["header_matches_manifest"] is True
    assert verify["members_verified"] is True


def test_describe_failure_keeps_its_complete_machine_shape(tmp_path: Path) -> None:
    output = io.StringIO()
    exit_code = bundle_command.main(
        ["describe", str(tmp_path / "private-name.cortexbundle"), "--json"],
        output=output,
    )
    payload = _payload(output)
    assert exit_code == EXIT_NOT_FOUND
    assert payload["status"] == "failed"
    assert payload["error"] == {
        "code": "archive_not_found",
        "phase": "open_archive",
        "path": None,
    }
    assert all(payload[field] is None for field in set(payload) - _COMMON_FIELDS)
    assert "private-name" not in output.getvalue()


def test_verify_authenticates_the_exact_clear_header_bytes(tmp_path: Path) -> None:
    archive = tmp_path / "header-altered.cortexbundle"
    _write_valid_archive(archive)
    with archive.open("rb") as stream:
        original = stream.read()

    def change_created_at(header: dict[str, object]) -> None:
        header["created_at"] = "2026-08-08T20:00:00Z"

    _rewrite_clear_header(archive, change_created_at)
    with archive.open("rb") as stream:
        changed = stream.read()
    assert len(changed) == len(original)
    assert sum(left != right for left, right in zip(original, changed, strict=True)) == 1
    output = io.StringIO()
    exit_code = bundle_command.main(
        ["verify", str(archive), "--json", "--password-stdin"],
        input_stream=io.StringIO(_PASSWORD + "\n"),
        output=output,
    )
    assert exit_code == EXIT_INTEGRITY
    assert _payload(output)["error"]["code"] == "authentication_failed"


def test_excessive_kdf_cost_is_rejected_before_derivation(tmp_path: Path) -> None:
    archive = tmp_path / "excessive-kdf.cortexbundle"
    _write_valid_archive(archive)

    def set_excessive_memory_cost(header: dict[str, object]) -> None:
        kdf = header["kdf"]
        assert isinstance(kdf, dict)
        kdf["memory_cost"] = 2_147_483_648

    _rewrite_clear_header(archive, set_excessive_memory_cost)
    output = io.StringIO()
    started = time.perf_counter()
    exit_code = bundle_command.main(
        ["verify", str(archive), "--json", "--password-stdin"],
        input_stream=io.StringIO(_PASSWORD + "\n"),
        output=output,
    )
    elapsed = time.perf_counter() - started
    assert exit_code == EXIT_INVALID_INPUT
    assert _payload(output)["error"]["code"] == "kdf_parameters_rejected"
    assert elapsed < 1.0


@pytest.mark.parametrize(("code", "expected_exit"), _ERROR_EXITS)
def test_each_verify_failure_has_one_closed_redacted_shape(
    code: BundleErrorCode,
    expected_exit: int,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    private_path = Path("C:/Users/private-account/private-name.cortexbundle")

    if code in {"archive_not_found", "archive_unreadable"}:
        def fail_open(_path: Path) -> io.BytesIO:
            raise BundleFormatError(code, "open_archive")

        monkeypatch.setattr(bundle_command, "_open_archive", fail_open)
    else:
        monkeypatch.setattr(bundle_command, "_open_archive", lambda _path: io.BytesIO())

    if code not in {"archive_not_found", "archive_unreadable", "password_missing"}:
        def fail_verify(*_args: object, **_kwargs: object) -> None:
            mismatch = False if code == "header_manifest_mismatch" else None
            raise BundleFormatError(
                code,
                "fixture_phase",
                header_matches_manifest=mismatch,
            )

        monkeypatch.setattr(bundle_command, "verify_bundle", fail_verify)

    password = "" if code == "password_missing" else _PASSWORD + "\n"
    output = io.StringIO()
    exit_code = bundle_command._verify(
        private_path,
        io.StringIO(password),
        output,
    )
    payload = _payload(output)
    assert exit_code == expected_exit
    assert payload["status"] == "failed"
    error = payload["error"]
    assert isinstance(error, dict)
    assert error["code"] == code
    assert error["path"] is None

    command_fields = set(payload) - _COMMON_FIELDS
    expected_exception = (
        {"header_matches_manifest": False}
        if code == "header_manifest_mismatch"
        else {}
    )
    assert {
        field: payload[field] for field in command_fields if payload[field] is not None
    } == expected_exception
    rendered = output.getvalue()
    assert "private-account" not in rendered
    assert "private-name" not in rendered
    assert capsys.readouterr().err == ""


def test_bundle_describe_ignores_invalid_user_config_and_does_not_import_it(
    tmp_path: Path,
) -> None:
    archive = tmp_path / "valid.cortexbundle"
    _write_valid_archive(archive)
    appdata = tmp_path / "appdata"
    config_directory = appdata / "Cortex"
    config_directory.mkdir(parents=True)
    (config_directory / "config.toml").write_text("invalid = [", encoding="utf-8")
    script = """
import contextlib
import io
import json
import sys
import cli

output = io.StringIO()
with contextlib.redirect_stdout(output):
    exit_code = cli.main(["bundle", "describe", sys.argv[1], "--json"])
print(json.dumps({
    "exit_code": exit_code,
    "report": json.loads(output.getvalue()),
    "config_imported": "config" in sys.modules,
    "user_config_imported": "user_config" in sys.modules,
    "writer_imported": "confluence_writer.writer" in sys.modules,
}))
"""
    environment = {
        **os.environ,
        "APPDATA": str(appdata),
        "LOCALAPPDATA": str(tmp_path / "localappdata"),
    }
    completed = subprocess.run(
        [sys.executable, "-c", script, str(archive)],
        cwd=_ROOT,
        env=environment,
        capture_output=True,
        text=True,
        check=False,
    )
    assert completed.returncode == 0, completed.stderr
    assert completed.stderr == ""
    result = json.loads(completed.stdout)
    assert result["exit_code"] == EXIT_OK
    assert result["report"]["claimed_compatible"] is True
    assert result["config_imported"] is False
    assert result["user_config_imported"] is False
    assert result["writer_imported"] is False


def test_confluence_writer_public_reexport_remains_available_in_fresh_process() -> None:
    script = """
import json
import sys
import confluence_writer

before = "confluence_writer.writer" in sys.modules
writer = confluence_writer.ConfluenceWriter
print(json.dumps({
    "before": before,
    "after": "confluence_writer.writer" in sys.modules,
    "name": writer.__name__,
}))
"""
    completed = subprocess.run(
        [sys.executable, "-c", script],
        cwd=_ROOT,
        capture_output=True,
        text=True,
        check=False,
    )
    assert completed.returncode == 0, completed.stderr
    assert completed.stderr == ""
    assert json.loads(completed.stdout) == {
        "before": False,
        "after": True,
        "name": "ConfluenceWriter",
    }
