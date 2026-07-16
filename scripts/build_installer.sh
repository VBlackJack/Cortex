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
# Build the standalone Cortex executable on Linux or macOS with PyInstaller.
# Install the build extra first: python -m pip install -e ".[build]".

set -euo pipefail

SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" >/dev/null 2>&1 && pwd)"
readonly SCRIPT_DIR
REPO_ROOT="$(cd -- "${SCRIPT_DIR}/.." >/dev/null 2>&1 && pwd)"
readonly REPO_ROOT
readonly ENTRY="${REPO_ROOT}/packaging/cortex_launcher.py"
readonly EXE_NAME="cortex"

PYTHON="python3"
OUTPUT_DIR="dist"
CLEAN=0

log()  { printf '[build] %s\n' "$*" >&2; }
fail() { printf '[build] ERROR: %s\n' "$*" >&2; exit 1; }

usage() {
  cat <<'EOF'
Usage: build_installer.sh [--python PATH] [--output DIR] [--clean] [--help]

  --python PATH   Python interpreter used to run PyInstaller (default: python3)
  --output DIR    Output directory for the executable (default: dist)
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

readonly WORK_PATH="${REPO_ROOT}/build/pyinstaller"
readonly DIST_PATH="${REPO_ROOT}/${OUTPUT_DIR}"

command -v "${PYTHON}" >/dev/null 2>&1 || fail "Python interpreter not found: ${PYTHON}"
[[ -f "${ENTRY}" ]] || fail "Entry script not found: ${ENTRY}"
"${PYTHON}" -c "import PyInstaller" >/dev/null 2>&1 \
  || fail "PyInstaller is not installed. Run: ${PYTHON} -m pip install -e \".[build]\""

if [[ "${CLEAN}" -eq 1 ]]; then
  log "Removing prior artifacts: ${WORK_PATH} ${DIST_PATH}"
  rm -rf -- "${WORK_PATH}" "${DIST_PATH}"
fi

log "Running PyInstaller."
"${PYTHON}" -m PyInstaller \
  --noconfirm \
  --onefile \
  --name "${EXE_NAME}" \
  --paths "${REPO_ROOT}" \
  --collect-all chromadb \
  --collect-all onnxruntime \
  --collect-all fastembed \
  --collect-all tokenizers \
  --hidden-import server \
  --hidden-import indexer \
  --hidden-import doctor \
  --hidden-import setup_wizard \
  --hidden-import setup_config \
  --hidden-import sync_hash_aware \
  --hidden-import sync_summary \
  --hidden-import lexical_index \
  --hidden-import reranker \
  --hidden-import chroma_client \
  --hidden-import chunker \
  --hidden-import chunker_pdf \
  --hidden-import chunker_utils \
  --hidden-import config \
  --hidden-import cortex_logging \
  --hidden-import data_home \
  --hidden-import dependencies \
  --hidden-import embedding_fingerprint \
  --hidden-import freshness \
  --hidden-import user_config \
  --hidden-import write_lock \
  --hidden-import truststore \
  --hidden-import _version \
  --distpath "${DIST_PATH}" \
  --workpath "${WORK_PATH}" \
  --specpath "${WORK_PATH}" \
  "${ENTRY}"

readonly EXE_PATH="${DIST_PATH}/${EXE_NAME}"
[[ -f "${EXE_PATH}" ]] || fail "Build reported success but ${EXE_PATH} is missing."
log "Built standalone executable: ${EXE_PATH}"
