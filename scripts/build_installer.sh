#!/usr/bin/env bash
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
#
# Build the standalone Cortex executable through the canonical Python builder.

set -euo pipefail

SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" >/dev/null 2>&1 && pwd)"
readonly SCRIPT_DIR
REPO_ROOT="$(cd -- "${SCRIPT_DIR}/.." >/dev/null 2>&1 && pwd)"
readonly REPO_ROOT
readonly BUILDER="${REPO_ROOT}/packaging/build_executable.py"

PYTHON="python3"
OUTPUT_DIR="dist"
CLEAN=0

log()  { printf '[build] %s\n' "$*" >&2; }
fail() { printf '[build] ERROR: %s\n' "$*" >&2; exit 1; }

usage() {
  cat <<'EOF'
Usage: build_installer.sh [--python PATH] [--output DIR] [--clean] [--help]

  --python PATH   Python interpreter used to run PyInstaller (default: python3)
  --output DIR    Dedicated output directory; must resolve to repository dist
  --clean         Remove prior build/output artifacts before building
  --help          Show this help and exit
EOF
}

while [[ $# -gt 0 ]]; do
  case "$1" in
    --python) PYTHON="${2:?--python requires a value}"; shift 2 ;;
    --output) OUTPUT_DIR="${2:?--output requires a value}"; shift 2 ;;
    --clean) CLEAN=1; shift ;;
    --help) usage; exit 0 ;;
    *) usage; fail "Unknown argument: $1" ;;
  esac
done

command -v "${PYTHON}" >/dev/null 2>&1 || fail "Python interpreter not found: ${PYTHON}"
[[ -f "${BUILDER}" ]] || fail "Canonical build script not found: ${BUILDER}"
"${PYTHON}" -c "import PyInstaller" >/dev/null 2>&1 \
  || fail "PyInstaller is not installed. Run: ${PYTHON} -m pip install -e \".[build]\""

BUILD_ARGUMENTS=("${BUILDER}" "--output-dir" "${OUTPUT_DIR}")
if [[ "${CLEAN}" -eq 1 ]]; then
  BUILD_ARGUMENTS+=("--clean")
fi
readonly BUILD_ARGUMENTS

log "Running the canonical PyInstaller build."
(
  cd -- "${REPO_ROOT}"
  "${PYTHON}" "${BUILD_ARGUMENTS[@]}"
)
