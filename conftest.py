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
"""
Pytest bootstrap: put the project root on sys.path and make the suite hermetic.
"""
import atexit
import logging
import os
import shutil
import sys
import tempfile
from collections.abc import Iterator

import pytest

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


@pytest.fixture(autouse=True, scope="session")
def _isolated_log_dir() -> Iterator[None]:
    """Keep the rotating log an in-process entry point opens out of the data home.

    configure_logging() resolves its directory from cortex_logging.CORTEX_LOG_DIR
    at call time. Left alone, that is the developer's real Cortex data home, so
    fixture errors would land in the file `cortex doctor` reads. The model cache
    shares that home, so the home itself must stay put; only the log moves.
    """
    import cortex_logging

    directory = tempfile.mkdtemp(prefix="cortex-test-logs-")
    with pytest.MonkeyPatch.context() as patcher:
        patcher.setattr(cortex_logging, "CORTEX_LOG_DIR", directory)
        yield
    shutil.rmtree(directory, ignore_errors=True)


@pytest.fixture(autouse=True)
def _restore_cortex_logger() -> Iterator[None]:
    """Detach the handlers an in-process entry point installs on the cortex logger.

    configure_logging() binds a stream handler to sys.stderr, which pytest swaps
    for a per-test capture stream. A handler left behind writes to a closed
    stream in every later test that logs through `cortex`, and the logger keeps
    propagate=False, which hides its records from caplog.
    """
    logger = logging.getLogger("cortex")
    handlers = list(logger.handlers)
    level = logger.level
    propagate = logger.propagate
    yield
    for handler in logger.handlers:
        if handler not in handlers:
            handler.close()
    logger.handlers[:] = handlers
    logger.setLevel(level)
    logger.propagate = propagate
