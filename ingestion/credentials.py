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
"""Read-only Windows Credential Manager access and expiry assessment."""

from __future__ import annotations

import ctypes
import logging
import os
from ctypes import wintypes
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Protocol, final

from ingestion.constants import (
    ACTION_RENEW_CREDENTIAL,
    ERROR_AUTH_EXPIRED,
    ERROR_AUTH_EXPIRES_SOON,
)
from ingestion.models import HealthStatus

_CRED_TYPE_GENERIC = 1
_CRED_PERSIST_LOCAL_MACHINE = 2
_LOG = logging.getLogger("cortex.ingestion.credentials")


class CredentialReadError(RuntimeError):
    """Raised without secret material when a credential cannot be read."""


class CredentialWriteError(RuntimeError):
    """Raised without secret material when a credential cannot be stored."""


@final
class SecretValue:
    """A secret value whose string representations are always redacted."""

    def __init__(self, value: str) -> None:
        """Wrap a non-empty value read from the operating-system vault."""
        if not value:
            raise CredentialReadError("Windows Credential Manager returned an empty value.")
        self._value = value

    def reveal(self) -> str:
        """Return the value only to the source adapter that needs authentication."""
        return self._value

    def __repr__(self) -> str:
        return "SecretValue('[REDACTED]')"

    def __str__(self) -> str:
        return "[REDACTED]"


class CredentialReader(Protocol):
    """Read a generic credential without offering any write operation."""

    def read(self, target_name: str) -> SecretValue:
        """Read one named credential from the operating-system vault."""
        ...


class CredentialWriter(Protocol):
    """Store a generic credential without accepting clear text as a CLI argument."""

    def write(self, target_name: str, secret: SecretValue) -> None:
        """Write one named credential to the operating-system vault."""
        ...


class _CredentialW(ctypes.Structure):
    _fields_ = [
        ("Flags", wintypes.DWORD),
        ("Type", wintypes.DWORD),
        ("TargetName", wintypes.LPWSTR),
        ("Comment", wintypes.LPWSTR),
        ("LastWritten", wintypes.FILETIME),
        ("CredentialBlobSize", wintypes.DWORD),
        ("CredentialBlob", ctypes.POINTER(ctypes.c_ubyte)),
        ("Persist", wintypes.DWORD),
        ("AttributeCount", wintypes.DWORD),
        ("Attributes", ctypes.c_void_p),
        ("TargetAlias", wintypes.LPWSTR),
        ("UserName", wintypes.LPWSTR),
    ]


@final
class WindowsCredentialReader:
    """Read generic credentials through the native CredReadW API."""

    def read(self, target_name: str) -> SecretValue:
        """Read one generic credential and free the native allocation."""
        if os.name != "nt":
            raise CredentialReadError("Windows Credential Manager is unavailable.")
        if not target_name.strip():
            raise CredentialReadError("Credential target name must not be empty.")
        advapi32 = ctypes.WinDLL("Advapi32.dll", use_last_error=True)
        credential_pointer = ctypes.POINTER(_CredentialW)()
        cred_read = advapi32.CredReadW
        cred_read.argtypes = [
            wintypes.LPCWSTR,
            wintypes.DWORD,
            wintypes.DWORD,
            ctypes.POINTER(ctypes.POINTER(_CredentialW)),
        ]
        cred_read.restype = wintypes.BOOL
        cred_free = advapi32.CredFree
        cred_free.argtypes = [ctypes.c_void_p]
        cred_free.restype = None
        if not cred_read(
            target_name,
            _CRED_TYPE_GENERIC,
            0,
            ctypes.byref(credential_pointer),
        ):
            error_code = ctypes.get_last_error()
            _LOG.error(
                "credential_read_failed target=%s system_error=%d",
                target_name,
                error_code,
            )
            raise CredentialReadError(
                f"Windows Credential Manager read failed with system error {error_code}."
            )
        try:
            credential = credential_pointer.contents
            raw = ctypes.string_at(
                credential.CredentialBlob,
                credential.CredentialBlobSize,
            )
            try:
                value = raw.decode("utf-16-le")
            except UnicodeDecodeError:
                value = raw.decode("utf-8", errors="strict")
            _LOG.info("credential_read_succeeded target=%s", target_name)
            return SecretValue(value)
        finally:
            cred_free(credential_pointer)


@final
class WindowsCredentialWriter:
    """Write generic credentials through the native CredWriteW API."""

    def write(self, target_name: str, secret: SecretValue) -> None:
        """Persist one UTF-16 generic credential for the current Windows user."""
        if os.name != "nt":
            raise CredentialWriteError("Windows Credential Manager is unavailable.")
        if not target_name.strip():
            raise CredentialWriteError("Credential target name must not be empty.")
        raw = secret.reveal().encode("utf-16-le", errors="strict")
        if len(raw) > 2560:
            raise CredentialWriteError("Credential value exceeds the Windows generic limit.")
        blob = ctypes.create_string_buffer(raw)
        credential = _CredentialW()
        credential.Type = _CRED_TYPE_GENERIC
        credential.TargetName = target_name
        credential.Comment = "Cortex Confluence personal access token"
        credential.CredentialBlobSize = len(raw)
        credential.CredentialBlob = ctypes.cast(blob, ctypes.POINTER(ctypes.c_ubyte))
        credential.Persist = _CRED_PERSIST_LOCAL_MACHINE
        credential.UserName = "Cortex"
        advapi32 = ctypes.WinDLL("Advapi32.dll", use_last_error=True)
        cred_write = advapi32.CredWriteW
        cred_write.argtypes = [ctypes.POINTER(_CredentialW), wintypes.DWORD]
        cred_write.restype = wintypes.BOOL
        if not cred_write(ctypes.byref(credential), 0):
            error_code = ctypes.get_last_error()
            _LOG.error(
                "credential_write_failed target=%s system_error=%d",
                target_name,
                error_code,
            )
            raise CredentialWriteError(
                f"Windows Credential Manager write failed with system error {error_code}."
            )
        _LOG.info("credential_write_succeeded target=%s", target_name)


@dataclass(frozen=True)
class CredentialCheck:
    """Credential availability and expiry without serialized secret material."""

    status: HealthStatus
    error_code: str | None
    action_required: str | None
    secret: SecretValue | None


def check_credential(
    reader: CredentialReader,
    *,
    target_name: str,
    auth_expires_at: datetime,
    warning_days: int,
    now: datetime,
) -> CredentialCheck:
    """Read a secret and fail closed when its declared lifetime has ended."""
    if warning_days < 1:
        raise ValueError("warning_days must be at least one")
    if now.tzinfo is None or now.utcoffset() is None:
        raise ValueError("now must include a UTC offset")
    if auth_expires_at.tzinfo is None or auth_expires_at.utcoffset() is None:
        raise ValueError("auth_expires_at must include a UTC offset")
    secret = reader.read(target_name)
    if auth_expires_at <= now:
        _LOG.error(
            "credential_expired target=%s auth_expires_at=%s",
            target_name,
            auth_expires_at.isoformat(),
        )
        return CredentialCheck(
            status=HealthStatus.ERROR,
            error_code=ERROR_AUTH_EXPIRED,
            action_required=ACTION_RENEW_CREDENTIAL,
            secret=None,
        )
    if auth_expires_at - now <= timedelta(days=warning_days):
        _LOG.warning(
            "credential_expires_soon target=%s auth_expires_at=%s warning_days=%d",
            target_name,
            auth_expires_at.isoformat(),
            warning_days,
        )
        return CredentialCheck(
            status=HealthStatus.DEGRADED,
            error_code=ERROR_AUTH_EXPIRES_SOON,
            action_required=ACTION_RENEW_CREDENTIAL,
            secret=secret,
        )
    _LOG.info(
        "credential_valid target=%s auth_expires_at=%s",
        target_name,
        auth_expires_at.isoformat(),
    )
    return CredentialCheck(
        status=HealthStatus.OK,
        error_code=None,
        action_required=None,
        secret=secret,
    )


__all__ = [
    "CredentialCheck",
    "CredentialReadError",
    "CredentialReader",
    "CredentialWriteError",
    "CredentialWriter",
    "SecretValue",
    "WindowsCredentialReader",
    "WindowsCredentialWriter",
    "check_credential",
]
