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
"""Retry and missed-window decisions owned by the ingestion CLI layer."""

from __future__ import annotations

import logging
import random
import re
import time
from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import TypeVar

from ingestion.constants import LOGGED_CAUSE_MAX_CHARS

_LOG = logging.getLogger("cortex.ingestion.scheduling")
ResultT = TypeVar("ResultT")


_URL_PATTERN = re.compile(r"[A-Za-z][A-Za-z0-9+.-]*://\S+")


class TransientIngestionError(RuntimeError):
    """Signals an operation that is safe to retry with bounded backoff."""


def describe_cause(exc: BaseException) -> tuple[str, str]:
    """Return the type name and a log-safe message of the exception's cause.

    URLs are replaced, because a query string may carry a credential, and the
    message is bounded. Headers never reach an exception message here.
    """
    cause = exc.__cause__
    if cause is None:
        return "none", ""
    message = _URL_PATTERN.sub("<url>", str(cause))
    return type(cause).__name__, message[:LOGGED_CAUSE_MAX_CHARS]


@dataclass(frozen=True)
class RetryPolicy:
    """Bounded exponential backoff configuration."""

    attempts: int
    initial_seconds: float
    maximum_seconds: float
    multiplier: float
    jitter_ratio: float

    def __post_init__(self) -> None:
        """Reject unbounded or negative retry settings."""
        if self.attempts < 1:
            raise ValueError("attempts must be at least one")
        if self.initial_seconds <= 0 or self.maximum_seconds < self.initial_seconds:
            raise ValueError("retry delays are invalid")
        if self.multiplier < 1:
            raise ValueError("multiplier must be at least one")
        if not 0 <= self.jitter_ratio <= 1:
            raise ValueError("jitter_ratio must be between zero and one")


def catch_up_due(
    *,
    last_success_at: datetime | None,
    now: datetime,
    interval_seconds: float,
) -> bool:
    """Return whether startup must catch up a missed scheduled window."""
    if interval_seconds <= 0:
        raise ValueError("interval_seconds must be greater than zero")
    if now.tzinfo is None or now.utcoffset() is None:
        raise ValueError("now must include a UTC offset")
    if last_success_at is None:
        return True
    if last_success_at.tzinfo is None or last_success_at.utcoffset() is None:
        raise ValueError("last_success_at must include a UTC offset")
    return now - last_success_at >= timedelta(seconds=interval_seconds)


def run_with_backoff(
    operation: Callable[[], ResultT],
    policy: RetryPolicy,
    *,
    sleep: Callable[[float], None] = time.sleep,
    random_unit: Callable[[], float] = random.random,
) -> ResultT:
    """Retry only declared transient failures with exponential jitter."""
    delay = policy.initial_seconds
    for attempt_number in range(1, policy.attempts + 1):
        try:
            return operation()
        except TransientIngestionError as exc:
            cause_type, cause_message = describe_cause(exc)
            if attempt_number == policy.attempts:
                _LOG.error(
                    "ingestion_retry_exhausted attempts=%d cause_type=%s cause=%s",
                    policy.attempts,
                    cause_type,
                    cause_message,
                )
                raise
            centered_random = (random_unit() * 2.0) - 1.0
            wait_seconds = max(0.0, delay * (1.0 + policy.jitter_ratio * centered_random))
            _LOG.warning(
                "ingestion_transient_retry attempt=%d next_delay_s=%.3f "
                "cause_type=%s cause=%s",
                attempt_number,
                wait_seconds,
                cause_type,
                cause_message,
            )
            sleep(wait_seconds)
            delay = min(policy.maximum_seconds, delay * policy.multiplier)
    raise AssertionError("retry loop did not return or raise")


__all__ = [
    "RetryPolicy",
    "TransientIngestionError",
    "catch_up_due",
    "describe_cause",
    "run_with_backoff",
]
