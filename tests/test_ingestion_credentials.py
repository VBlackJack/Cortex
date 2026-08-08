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
"""Platform-boundary tests for Windows Credential Manager access."""

from __future__ import annotations

from types import SimpleNamespace

import pytest

import ingestion.credentials as credentials
from ingestion.credentials import (
    CredentialReadError,
    CredentialWriteError,
    SecretValue,
    WindowsCredentialReader,
    WindowsCredentialWriter,
)


@pytest.fixture
def non_windows_boundary(monkeypatch: pytest.MonkeyPatch) -> None:
    """Expose a non-Windows platform and forbid every native library load."""
    monkeypatch.setattr(credentials, "os", SimpleNamespace(name="posix"))

    def unexpected_native_load(*_args: object, **_kwargs: object) -> None:
        pytest.fail("non-Windows credential access attempted to load a native library")

    monkeypatch.setattr(credentials.ctypes, "WinDLL", unexpected_native_load, raising=False)


def test_windows_credential_reader_fails_closed_off_windows(
    non_windows_boundary: None,
) -> None:
    with pytest.raises(CredentialReadError, match="unavailable"):
        WindowsCredentialReader().read("fixture-target")


def test_windows_credential_writer_fails_closed_off_windows(
    non_windows_boundary: None,
) -> None:
    with pytest.raises(CredentialWriteError, match="unavailable"):
        WindowsCredentialWriter().write("fixture-target", SecretValue("fixture-secret"))
