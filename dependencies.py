# Copyright 2026 Julien Bombled
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
"""Shared runtime dependency contract for setup and diagnostics."""

from __future__ import annotations

import sys

REQUIRED_PACKAGES = [
    "mcp",
    "chromadb",
    "fastembed",
    "pydantic",
    "pdfplumber",
    "filelock",
]
if sys.version_info < (3, 11):
    REQUIRED_PACKAGES.append("tomli")
