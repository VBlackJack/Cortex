# Copyright 2026 Julien Bombled
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
"""Cortex stderr and bounded rotating-file logging configuration."""

from __future__ import annotations

import logging
import sys
from logging.handlers import RotatingFileHandler
from pathlib import Path

from config import (
    CORTEX_LOG_DIR,
    LOG_BACKUP_COUNT,
    LOG_FILE_NAME,
    LOG_MAX_BYTES,
)

_HANDLER_MARKER = "_cortex_managed_handler"


def configure_logging(
    *,
    log_dir: str | Path = CORTEX_LOG_DIR,
    logger_name: str = "cortex",
    level: int = logging.INFO,
    max_bytes: int = LOG_MAX_BYTES,
    backup_count: int = LOG_BACKUP_COUNT,
) -> logging.Logger:
    """Configure stderr plus rotating logs without duplicating handlers.

    Callers must log operational metadata only: paths, statuses and counters,
    never document or chunk contents.
    """
    target = logging.getLogger(logger_name)
    target.setLevel(level)
    target.propagate = False
    if any(getattr(handler, _HANDLER_MARKER, False) for handler in target.handlers):
        return target

    directory = Path(log_dir)
    directory.mkdir(parents=True, exist_ok=True)
    formatter = logging.Formatter(
        "%(asctime)s %(levelname)s %(name)s %(message)s",
        datefmt="%Y-%m-%dT%H:%M:%S%z",
    )

    stderr_handler = logging.StreamHandler(sys.stderr)
    stderr_handler.setFormatter(formatter)
    setattr(stderr_handler, _HANDLER_MARKER, True)

    file_handler = RotatingFileHandler(
        directory / LOG_FILE_NAME,
        maxBytes=max_bytes,
        backupCount=backup_count,
        encoding="utf-8",
    )
    file_handler.setFormatter(formatter)
    setattr(file_handler, _HANDLER_MARKER, True)

    target.addHandler(stderr_handler)
    target.addHandler(file_handler)
    return target
