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
"""Confluence CLI secret-boundary, config precedence, and root routing tests."""

from __future__ import annotations

import logging
from collections.abc import Iterator
from pathlib import Path

import pytest

import cli
import confluence_writer.cli as confluence_cli
from confluence_writer.config import ConfluenceConfigError, load_confluence_settings
from ingestion.credentials import SecretValue

_FAKE_SECRET = "fixture-only-fake-secret-confluence-cli-47bf"


@pytest.fixture(autouse=True)
def restore_cortex_logger() -> Iterator[None]:
    """Prevent CLI logging handlers from leaking across the existing suite."""
    target = logging.getLogger("cortex")
    previous_level = target.level
    previous_propagate = target.propagate
    previous_handlers = list(target.handlers)
    try:
        yield
    finally:
        for handler in list(target.handlers):
            if handler not in previous_handlers:
                target.removeHandler(handler)
                handler.close()
        target.setLevel(previous_level)
        target.propagate = previous_propagate


class FakeCredentialWriter:
    """Record only target and redacted representation from the CLI prompt."""

    def __init__(self) -> None:
        self.target: str | None = None
        self.secret_repr: str | None = None

    def write(self, target_name: str, secret: SecretValue) -> None:
        self.target = target_name
        self.secret_repr = repr(secret)


def test_config_uses_environment_over_toml_over_defaults(tmp_path: Path) -> None:
    config_path = tmp_path / "confluence.toml"
    config_path.write_text(
        "schema_version = 1\n"
        'base_url = "https://toml.example.test"\n'
        "max_attachment_size_mb = 40\n"
        "[[spaces]]\n"
        'space_key = "DOC"\n'
        'target = "knowledge/doc"\n'
        'classification = "perso-non-sensible"\n',
        encoding="utf-8",
    )

    settings = load_confluence_settings(
        path=config_path,
        environ={
            "CORTEX_CONFLUENCE_BASE_URL": "https://env.example.test",
            "CORTEX_CONFLUENCE_MAX_ATTACHMENT_SIZE_MB": "60",
        },
    )

    assert settings.base_url == "https://env.example.test"
    assert settings.max_attachment_size_mb == 60
    assert settings.failure_threshold == 0.10
    assert settings.spaces[0].space_key == "DOC"

    with pytest.raises(ConfluenceConfigError, match="CORTEX_CONFLUENCE_PAT"):
        load_confluence_settings(
            path=tmp_path / "absent.toml",
            environ={"CORTEX_CONFLUENCE_PAT": _FAKE_SECRET},
        )


def test_v1_config_loads_as_whole_space_without_rewriting(tmp_path: Path) -> None:
    config_path = tmp_path / "confluence.toml"
    config_path.write_text(
        "schema_version = 1\n"
        "[[spaces]]\n"
        'space_key = "DOC"\n'
        'target = "knowledge/doc"\n'
        'classification = "perso-non-sensible"\n',
        encoding="utf-8",
    )
    before = config_path.read_bytes()

    settings = load_confluence_settings(path=config_path, environ={})

    assert settings.schema_version == 1
    assert settings.spaces[0].effective_selection == "whole_space"
    assert settings.spaces[0].pages is None
    assert config_path.read_bytes() == before


def test_v2_requires_explicit_selection_for_every_space(tmp_path: Path) -> None:
    config_path = tmp_path / "confluence.toml"
    config_path.write_text(
        "schema_version = 2\n"
        "[[spaces]]\n"
        'space_key = "DOC"\n'
        'target = "knowledge/doc"\n'
        'classification = "perso-non-sensible"\n',
        encoding="utf-8",
    )

    with pytest.raises(ConfluenceConfigError, match="requires selection for every space"):
        load_confluence_settings(path=config_path, environ={})


def test_v2_whole_space_rejects_present_pages_table(tmp_path: Path) -> None:
    config_path = tmp_path / "confluence.toml"
    config_path.write_text(
        "schema_version = 2\n"
        "[[spaces]]\n"
        'space_key = "DOC"\n'
        'target = "knowledge/doc"\n'
        'classification = "perso-non-sensible"\n'
        'selection = "whole_space"\n'
        "pages = []\n",
        encoding="utf-8",
    )

    with pytest.raises(ConfluenceConfigError, match="must not include a pages table"):
        load_confluence_settings(path=config_path, environ={})


def test_v2_pages_accepts_an_empty_selection(tmp_path: Path) -> None:
    config_path = tmp_path / "confluence.toml"
    config_path.write_text(
        "schema_version = 2\n"
        "[[spaces]]\n"
        'space_key = "DOC"\n'
        'target = "knowledge/doc"\n'
        'classification = "perso-non-sensible"\n'
        'selection = "pages"\n'
        "pages = []\n",
        encoding="utf-8",
    )

    settings = load_confluence_settings(path=config_path, environ={})

    assert settings.spaces[0].effective_selection == "pages"
    assert settings.spaces[0].selected_page_ids == ()


@pytest.mark.parametrize("page_id", ["", "page-1001"])
def test_v2_pages_rejects_non_numeric_or_empty_page_ids(
    tmp_path: Path,
    page_id: str,
) -> None:
    config_path = tmp_path / "confluence.toml"
    config_path.write_text(
        "schema_version = 2\n"
        "[[spaces]]\n"
        'space_key = "DOC"\n'
        'target = "knowledge/doc"\n'
        'classification = "perso-non-sensible"\n'
        'selection = "pages"\n'
        "[[spaces.pages]]\n"
        f'page_id = "{page_id}"\n',
        encoding="utf-8",
    )

    with pytest.raises(ConfluenceConfigError, match="non-empty numeric string"):
        load_confluence_settings(path=config_path, environ={})


def test_v2_pages_rejects_duplicate_ids_within_one_space(tmp_path: Path) -> None:
    config_path = tmp_path / "confluence.toml"
    config_path.write_text(
        "schema_version = 2\n"
        "[[spaces]]\n"
        'space_key = "DOC"\n'
        'target = "knowledge/doc"\n'
        'classification = "perso-non-sensible"\n'
        'selection = "pages"\n'
        "[[spaces.pages]]\n"
        'page_id = "1001"\n'
        "[[spaces.pages]]\n"
        'page_id = "1001"\n',
        encoding="utf-8",
    )

    with pytest.raises(ConfluenceConfigError, match="duplicate page_id"):
        load_confluence_settings(path=config_path, environ={})


def test_store_credential_accepts_secret_only_from_getpass_and_redacts_output(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    writer = FakeCredentialWriter()
    monkeypatch.setattr(confluence_cli.getpass, "getpass", lambda _prompt: _FAKE_SECRET)
    monkeypatch.setattr(confluence_cli, "WindowsCredentialWriter", lambda: writer)

    exit_code = confluence_cli.main(["store-credential"])
    captured = capsys.readouterr()

    assert exit_code == 0
    assert writer.target == "cortex-spike"
    assert writer.secret_repr == "SecretValue('[REDACTED]')"
    assert _FAKE_SECRET not in captured.out
    assert _FAKE_SECRET not in captured.err


def test_sync_stops_before_credentials_when_metadata_v2_is_absent(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    config_path = tmp_path / "confluence.toml"
    config_path.write_text(
        "schema_version = 1\n"
        'base_url = "https://confluence.example.test"\n'
        'auth_expires_at = "2026-11-01T00:00:00+01:00"\n'
        'console_path = "fixture-console.exe"\n'
        "[[spaces]]\n"
        'space_key = "DOC"\n'
        'target = "knowledge/doc"\n'
        'classification = "perso-non-sensible"\n',
        encoding="utf-8",
    )
    ingestion_root = tmp_path / "ingestion"
    ingestion_config_path = tmp_path / "ingestion.toml"
    ingestion_config_path.write_text(
        f'schema_version = 1\ndata_root = "{ingestion_root.as_posix()}"\n',
        encoding="utf-8",
    )

    def unexpected_boundary_call(*_args: object, **_kwargs: object) -> None:
        pytest.fail("metadata gate crossed a credential or network boundary")

    monkeypatch.setattr(confluence_cli, "_rechunk_v2_ready", lambda: False)
    monkeypatch.setattr(confluence_cli, "WindowsCredentialReader", unexpected_boundary_call)
    monkeypatch.setattr(confluence_cli, "ConfluenceWriter", unexpected_boundary_call)

    exit_code = confluence_cli.main(
        [
            "--config",
            str(config_path),
            "--ingestion-config",
            str(ingestion_config_path),
            "sync",
            "--force",
        ]
    )

    assert exit_code == 1
    assert "metadata v2 rechunk is not deployed" in capsys.readouterr().err
    assert not ingestion_root.exists()


def test_root_cli_routes_confluence_arguments(monkeypatch: pytest.MonkeyPatch) -> None:
    received: list[str] = []

    def run(arguments: list[str]) -> int:
        received.extend(arguments)
        return 7

    monkeypatch.setattr(confluence_cli, "main", run)

    assert cli.main(["confluence", "store-credential"]) == 7
    assert received == ["store-credential"]
