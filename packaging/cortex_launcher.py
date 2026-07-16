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
"""PyInstaller entry point for the standalone Cortex executable."""

from __future__ import annotations

try:
    import truststore

    truststore.inject_into_ssl()
except Exception as exc:  # noqa: BLE001 -- bootstrap failure must not prevent startup.
    import sys

    print(f"[cortex] truststore injection failed: {exc}", file=sys.stderr)

from offline_models import activate_if_embedded

activate_if_embedded()

from cli import main  # noqa: E402

if __name__ == "__main__":
    raise SystemExit(main())
