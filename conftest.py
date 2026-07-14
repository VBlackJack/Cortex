# Copyright 2026 Julien Bombled
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
"""
Pytest bootstrap: put the project root on sys.path and make the suite hermetic.
"""
import atexit
import os
import shutil
import sys
import tempfile

ROOT = os.path.dirname(os.path.abspath(__file__))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

# Cortex resolves KB_PATH once, at import time, from the environment or the
# user's config.toml. On a clean machine (CI) that leaves it unset, so tests
# that chunk or read freshness fail with "Missing required 'kb_path'"; they pass
# only where a developer happens to have Cortex configured. Provide a throwaway
# kb_path (unless one is already set) before any Cortex module is imported, so
# tests never depend on an ambient vault.
if "CORTEX_KB_PATH" not in os.environ:
    _KB_TMP = tempfile.mkdtemp(prefix="cortex-test-kb-")
    os.environ["CORTEX_KB_PATH"] = _KB_TMP
    atexit.register(shutil.rmtree, _KB_TMP, ignore_errors=True)
