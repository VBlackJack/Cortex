#!/usr/bin/env bash
#
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
# mcp_registry_publish.sh — Publish the committed Cortex server descriptor.
# Usage: ./scripts/mcp_registry_publish.sh [--dry-run] [--verbose]

set -euo pipefail
IFS=$'\n\t'

readonly E_SUCCESS=0
readonly E_FAILURE=1
DRY_RUN="${DRY_RUN:-false}"
VALIDATE_ONLY="${VALIDATE_ONLY:-false}"
LOG_VERBOSE="${LOG_VERBOSE:-false}"
WORK_DIR=""
HTTP_STATUS=""
CURL_EXIT=0

log_info() { printf '[%s] [INFO] %s\n' "$(date '+%Y-%m-%d %H:%M:%S')" "$*" >&2; }
log_warn() { printf '[%s] [WARN] %s\n' "$(date '+%Y-%m-%d %H:%M:%S')" "$*" >&2; }
log_error() { printf '[%s] [ERROR] %s\n' "$(date '+%Y-%m-%d %H:%M:%S')" "$*" >&2; }
log_debug() {
  if [[ "${LOG_VERBOSE}" == "true" ]]; then
    printf '[%s] [DEBUG] %s\n' "$(date '+%Y-%m-%d %H:%M:%S')" "$*" >&2
  fi
}
log_success() { printf '[%s] [OK] %s\n' "$(date '+%Y-%m-%d %H:%M:%S')" "$*" >&2; }

fail() {
  log_error "$*"
  exit "${E_FAILURE}"
}

cleanup() {
  local exit_code=$?
  if [[ -n "${WORK_DIR}" && -d "${WORK_DIR}" ]]; then
    rm -rf -- "${WORK_DIR}"
  fi
  if [[ "${exit_code}" -ne "${E_SUCCESS}" ]]; then
    log_error "Registry publication failed with exit code ${exit_code}."
  fi
}
trap cleanup EXIT

usage() {
  cat <<'EOF'
Usage: mcp_registry_publish.sh [OPTIONS]

Wait for the exact Cortex PyPI version, verify the matching MCP Registry state,
then publish the committed server.json with the pinned official publisher.

Options:
  -n, --dry-run   Run every read-only check but do not authenticate or publish.
      --validate-only
                  Download the pinned publisher and validate server.json only.
  -v, --verbose   Enable debug logging.
  -h, --help      Show this help message.

All network endpoints, identities, timeouts, and publisher pins are supplied
through the environment by the release workflow.
EOF
}

parse_args() {
  while [[ $# -gt 0 ]]; do
    case "$1" in
      -n|--dry-run)
        DRY_RUN="true"
        shift
        ;;
      -v|--verbose)
        LOG_VERBOSE="true"
        shift
        ;;
      --validate-only)
        VALIDATE_ONLY="true"
        shift
        ;;
      -h|--help)
        usage
        exit "${E_SUCCESS}"
        ;;
      *)
        log_error "Unknown option: $1"
        usage >&2
        exit "${E_FAILURE}"
        ;;
    esac
  done
}

require_env() {
  local name="$1"
  [[ -n "${!name:-}" ]] || fail "Required environment variable is empty: ${name}"
}

require_positive_integer() {
  local name="$1"
  local value="$2"
  [[ "${value}" =~ ^[1-9][0-9]*$ ]] || fail "${name} must be a positive integer."
}

require_nonnegative_integer() {
  local name="$1"
  local value="$2"
  [[ "${value}" =~ ^[0-9]+$ ]] || fail "${name} must be a non-negative integer."
}

check_prerequisites() {
  local required_name
  local required_command
  local required_names=(
    MCP_SERVER_JSON_PATH
    MCP_SERVER_NAME
    PYPI_PACKAGE
    PYPI_API_BASE_URL
    MCP_REGISTRY_API_BASE_URL
    MCP_PUBLISHER_DOWNLOAD_BASE_URL
    MCP_PUBLISHER_VERSION
    MCP_PUBLISHER_ASSET
    MCP_PUBLISHER_SHA256
    MCP_PYPI_POLL_ATTEMPTS
    MCP_PYPI_POLL_INTERVAL_SECONDS
    MCP_CURL_CONNECT_TIMEOUT_SECONDS
    MCP_CURL_MAX_TIME_SECONDS
    MCP_DOWNLOAD_MAX_TIME_SECONDS
  )

  for required_name in "${required_names[@]}"; do
    require_env "${required_name}"
  done

  require_positive_integer "MCP_PYPI_POLL_ATTEMPTS" "${MCP_PYPI_POLL_ATTEMPTS}"
  require_nonnegative_integer \
    "MCP_PYPI_POLL_INTERVAL_SECONDS" \
    "${MCP_PYPI_POLL_INTERVAL_SECONDS}"
  require_positive_integer \
    "MCP_CURL_CONNECT_TIMEOUT_SECONDS" \
    "${MCP_CURL_CONNECT_TIMEOUT_SECONDS}"
  require_positive_integer "MCP_CURL_MAX_TIME_SECONDS" "${MCP_CURL_MAX_TIME_SECONDS}"
  require_positive_integer "MCP_DOWNLOAD_MAX_TIME_SECONDS" "${MCP_DOWNLOAD_MAX_TIME_SECONDS}"
  [[ "${MCP_PUBLISHER_SHA256}" =~ ^[0-9a-f]{64}$ ]] \
    || fail "MCP_PUBLISHER_SHA256 must be a lowercase SHA-256 digest."

  for required_command in curl jq sha256sum tar mktemp; do
    command -v "${required_command}" >/dev/null 2>&1 \
      || fail "Required command not found: ${required_command}"
  done
  [[ -f "${MCP_SERVER_JSON_PATH}" ]] \
    || fail "server.json not found: ${MCP_SERVER_JSON_PATH}"
}

http_get_json() {
  local url="$1"
  local output_path="$2"

  HTTP_STATUS=""
  CURL_EXIT=0
  if HTTP_STATUS="$(
    curl \
      --silent \
      --fail-with-body \
      --show-error \
      --location \
      --connect-timeout "${MCP_CURL_CONNECT_TIMEOUT_SECONDS}" \
      --max-time "${MCP_CURL_MAX_TIME_SECONDS}" \
      --header 'Accept: application/json' \
      --output "${output_path}" \
      --write-out '%{http_code}' \
      "${url}"
  )"; then
    CURL_EXIT=0
  else
    CURL_EXIT=$?
  fi
  HTTP_STATUS="${HTTP_STATUS:-000}"
  log_debug "GET ${url}: HTTP ${HTTP_STATUS}, curl ${CURL_EXIT}."
}

urlencode() {
  jq -nr --arg value "$1" '$value | @uri'
}

wait_for_pypi() {
  local attempt
  local published_version
  local response_path="${WORK_DIR}/pypi-response.json"
  local url="${PYPI_API_BASE_URL%/}/${PYPI_PACKAGE}/${SERVER_VERSION}/json"

  for ((attempt = 1; attempt <= MCP_PYPI_POLL_ATTEMPTS; attempt += 1)); do
    log_info "PyPI check ${attempt}/${MCP_PYPI_POLL_ATTEMPTS}: ${PYPI_PACKAGE} ${SERVER_VERSION}."
    http_get_json "${url}" "${response_path}"

    if [[ "${CURL_EXIT}" -eq 0 && "${HTTP_STATUS}" == "200" ]]; then
      jq -e . "${response_path}" >/dev/null 2>&1 \
        || fail "PyPI returned invalid JSON for ${PYPI_PACKAGE} ${SERVER_VERSION}."
      published_version="$(jq -er '.info.version | select(type == "string")' "${response_path}")" \
        || fail "PyPI response does not contain info.version."
      [[ "${published_version}" == "${SERVER_VERSION}" ]] \
        || fail "PyPI returned version ${published_version}, expected ${SERVER_VERSION}."
      log_success "Exact PyPI version is available."
      return 0
    fi

    case "${HTTP_STATUS}" in
      000|404|429|5??)
        log_warn "PyPI version is not available yet (HTTP ${HTTP_STATUS}, curl ${CURL_EXIT})."
        ;;
      *)
        fail "PyPI check failed (HTTP ${HTTP_STATUS}, curl ${CURL_EXIT})."
        ;;
    esac

    if [[ "${attempt}" -eq "${MCP_PYPI_POLL_ATTEMPTS}" ]]; then
      fail "PyPI version did not become available within the bounded poll budget."
    fi
    sleep "${MCP_PYPI_POLL_INTERVAL_SECONDS}"
  done
}

registry_version_exists() {
  local encoded_name
  local encoded_version
  local response_path="${WORK_DIR}/registry-response.json"
  local url

  encoded_name="$(urlencode "${MCP_SERVER_NAME}")"
  encoded_version="$(urlencode "${SERVER_VERSION}")"
  url="${MCP_REGISTRY_API_BASE_URL%/}/v0.1/servers/${encoded_name}/versions/${encoded_version}"

  log_info "Registry pre-check: ${MCP_SERVER_NAME} ${SERVER_VERSION}."
  http_get_json "${url}" "${response_path}"

  if [[ "${CURL_EXIT}" -eq 0 && "${HTTP_STATUS}" == "200" ]]; then
    jq -e . "${response_path}" >/dev/null 2>&1 \
      || fail "Registry returned invalid JSON for an HTTP 200 response."
    jq -e \
      --arg name "${MCP_SERVER_NAME}" \
      --arg version "${SERVER_VERSION}" \
      '.server.name == $name and .server.version == $version' \
      "${response_path}" >/dev/null \
      || fail "Registry HTTP 200 response did not confirm the exact server version."
    log_success "Exact server version is already published."
    return 0
  fi

  if [[ "${CURL_EXIT}" -eq 22 && "${HTTP_STATUS}" == "404" ]]; then
    jq -e '
      (.error? | type == "string" and length > 0) or
      (
        .status? == 404 and
        (.title? | type == "string" and length > 0) and
        (.detail? | type == "string" and length > 0)
      )' "${response_path}" >/dev/null 2>&1 \
      || fail "Registry HTTP 404 response was not valid, unambiguous JSON."
    log_info "Exact server version is confirmed absent."
    return 1
  fi

  fail "Registry pre-check failed (HTTP ${HTTP_STATUS}, curl ${CURL_EXIT})."
}

install_publisher() {
  local archive_path="${WORK_DIR}/${MCP_PUBLISHER_ASSET}"
  local download_url
  local publisher_path="${WORK_DIR}/mcp-publisher"

  download_url="${MCP_PUBLISHER_DOWNLOAD_BASE_URL%/}/${MCP_PUBLISHER_VERSION}/${MCP_PUBLISHER_ASSET}"
  log_info "Downloading pinned mcp-publisher ${MCP_PUBLISHER_VERSION}."
  curl \
    --silent \
    --fail \
    --show-error \
    --location \
    --connect-timeout "${MCP_CURL_CONNECT_TIMEOUT_SECONDS}" \
    --max-time "${MCP_DOWNLOAD_MAX_TIME_SECONDS}" \
    --output "${archive_path}" \
    "${download_url}" \
    || fail "Could not download pinned mcp-publisher asset."

  printf '%s  %s\n' "${MCP_PUBLISHER_SHA256}" "${archive_path}" \
    | sha256sum --check --status - \
    || fail "mcp-publisher SHA-256 verification failed."
  log_success "mcp-publisher SHA-256 verified."

  tar -xzf "${archive_path}" -C "${WORK_DIR}" mcp-publisher \
    || fail "Could not extract mcp-publisher after checksum verification."
  [[ -f "${publisher_path}" ]] || fail "mcp-publisher was not present in the archive."
  chmod +x "${publisher_path}"
  printf '%s\n' "${publisher_path}"
}

main() {
  local manifest_fields
  local manifest_server_name
  local publisher_path

  parse_args "$@"
  check_prerequisites

  manifest_fields="$(jq -er \
    --arg package "${PYPI_PACKAGE}" \
    '.version as $version |
     select(.name | type == "string" and length > 0) |
     select($version | type == "string" and length > 0) |
     select(any(.packages[]?;
       .registryType == "pypi" and
       .identifier == $package and
       .version == $version)) |
     [.name, $version] | @tsv' \
    "${MCP_SERVER_JSON_PATH}")" \
    || fail "server.json does not contain a coherent target PyPI package version."

  IFS=$'\t' read -r manifest_server_name SERVER_VERSION <<<"${manifest_fields}"
  export SERVER_VERSION
  [[ "${manifest_server_name}" == "${MCP_SERVER_NAME}" ]] \
    || fail "server.json name does not match MCP_SERVER_NAME."

  WORK_DIR="$(mktemp -d)"
  publisher_path="$(install_publisher)"
  log_info "Validating committed server metadata."
  "${publisher_path}" validate "${MCP_SERVER_JSON_PATH}" \
    || fail "mcp-publisher rejected server.json."
  log_success "Committed server metadata is valid."
  if [[ "${VALIDATE_ONLY}" == "true" ]]; then
    exit "${E_SUCCESS}"
  fi

  wait_for_pypi
  if registry_version_exists; then
    exit "${E_SUCCESS}"
  fi

  if [[ "${DRY_RUN}" == "true" ]]; then
    log_warn "DRY-RUN: exact version is absent; authentication and publication were skipped."
    exit "${E_SUCCESS}"
  fi

  log_info "Authenticating to the MCP Registry with GitHub OIDC."
  "${publisher_path}" login github-oidc \
    || fail "mcp-publisher GitHub OIDC authentication failed."

  log_info "Publishing ${MCP_SERVER_NAME} ${SERVER_VERSION}."
  "${publisher_path}" publish "${MCP_SERVER_JSON_PATH}" \
    || fail "mcp-publisher publish failed."
  log_success "MCP Registry publication completed."
}

main "$@"
