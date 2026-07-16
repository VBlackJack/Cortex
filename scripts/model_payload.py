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
"""Acquire, attest and stage Cortex's portable offline model cache."""

from __future__ import annotations

import argparse
import hashlib
import importlib.metadata
import json
import math
import os
import shutil
import socket
import sys
import tempfile
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any, cast
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from offline_models import MANIFEST_FILENAME, manifest_entries, verify_manifest  # noqa: E402

DEFAULT_LOCK_PATH = ROOT / "models.lock"
DEFAULT_MANIFEST_PATH = ROOT / "models" / MANIFEST_FILENAME
SNAPSHOT_ENV = "CORTEX_MODEL_SNAPSHOT_DIR"
LOCK_SCHEMA_VERSION = 1
FASTEMBED_BASE_RUNTIME_FILES = frozenset(
    {
        "config.json",
        "special_tokens_map.json",
        "tokenizer.json",
        "tokenizer_config.json",
    }
)

SnapshotDownloader = Callable[..., str]


class ModelPayloadError(RuntimeError):
    """Raised when a model lock, snapshot or payload is unsafe or incomplete."""


@dataclass(frozen=True)
class ModelPin:
    """One immutable Hugging Face source in the model lock."""

    role: str
    product_id: str
    repository: str
    revision: str
    license_id: str
    required_files: tuple[str, ...]

    @property
    def cache_name(self) -> str:
        """Return the Hugging Face cache directory for this repository."""
        return f"models--{self.repository.replace('/', '--')}"


@dataclass(frozen=True)
class ModelLock:
    """Validated, versioned model acquisition contract."""

    fastembed_version: str
    huggingface_hub_version: str
    models: tuple[ModelPin, ...]


def _required_string(data: dict[str, Any], key: str, context: str) -> str:
    value = data.get(key)
    if not isinstance(value, str) or not value.strip():
        raise ModelPayloadError(f"{context} must contain a non-empty string '{key}'.")
    return value.strip()


def load_lock(path: Path = DEFAULT_LOCK_PATH) -> ModelLock:
    """Load and strictly validate the committed model lock."""
    try:
        raw: object = json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise ModelPayloadError(f"Could not read model lock '{path}': {exc}") from exc
    if not isinstance(raw, dict):
        raise ModelPayloadError(f"Model lock '{path}' must contain a JSON object.")
    data = cast(dict[str, Any], raw)
    if data.get("schema_version") != LOCK_SCHEMA_VERSION:
        raise ModelPayloadError(
            f"Model lock '{path}' must use schema_version {LOCK_SCHEMA_VERSION}."
        )
    fastembed_version = _required_string(data, "fastembed_version", "Model lock")
    hub_version = _required_string(data, "huggingface_hub_version", "Model lock")
    raw_models = data.get("models")
    if not isinstance(raw_models, list) or not raw_models:
        raise ModelPayloadError("Model lock must contain a non-empty 'models' list.")

    pins: list[ModelPin] = []
    roles: set[str] = set()
    repositories: set[str] = set()
    for index, raw_model in enumerate(raw_models):
        context = f"models[{index}]"
        if not isinstance(raw_model, dict):
            raise ModelPayloadError(f"{context} must contain a JSON object.")
        model = cast(dict[str, Any], raw_model)
        role = _required_string(model, "role", context)
        product_id = _required_string(model, "product_id", context)
        repository = _required_string(model, "repository", context)
        revision = _required_string(model, "revision", context).lower()
        license_id = _required_string(model, "license", context)
        required_files = model.get("required_files")
        if role in roles:
            raise ModelPayloadError(f"Model lock contains duplicate role '{role}'.")
        if repository in repositories:
            raise ModelPayloadError(
                f"Model lock contains duplicate repository '{repository}'."
            )
        if len(repository.split("/")) != 2 or any(not part for part in repository.split("/")):
            raise ModelPayloadError(f"{context} has invalid repository '{repository}'.")
        if len(revision) != 40 or any(
            character not in "0123456789abcdef" for character in revision
        ):
            raise ModelPayloadError(f"{context} has invalid 40-character revision '{revision}'.")
        if (
            not isinstance(required_files, list)
            or not required_files
            or any(not isinstance(item, str) or not item for item in required_files)
        ):
            raise ModelPayloadError(
                f"{context} must contain a non-empty string list 'required_files'."
            )
        pins.append(
            ModelPin(
                role=role,
                product_id=product_id,
                repository=repository,
                revision=revision,
                license_id=license_id,
                required_files=tuple(cast(list[str], required_files)),
            )
        )
        roles.add(role)
        repositories.add(repository)
    return ModelLock(
        fastembed_version=fastembed_version,
        huggingface_hub_version=hub_version,
        models=tuple(pins),
    )


def _require_empty_directory(path: Path) -> Path:
    resolved = Path(path).resolve()
    if resolved.exists() and any(resolved.iterdir()):
        raise ModelPayloadError(f"Output directory must be empty: '{resolved}'.")
    resolved.mkdir(parents=True, exist_ok=True)
    return resolved


def _snapshot_download() -> SnapshotDownloader:
    try:
        from huggingface_hub import snapshot_download
    except ImportError as exc:  # pragma: no cover - actionable build failure
        raise ModelPayloadError(
            "huggingface_hub is required to fetch model snapshots."
        ) from exc
    return cast(SnapshotDownloader, snapshot_download)


def fetch_models(
    output_dir: Path,
    *,
    lock_path: Path = DEFAULT_LOCK_PATH,
    downloader: SnapshotDownloader | None = None,
) -> Path:
    """Fetch pinned FastEmbed runtime files into a portable HF cache."""
    lock = load_lock(lock_path)
    output = _require_empty_directory(output_dir)
    download = _snapshot_download() if downloader is None else downloader
    with tempfile.TemporaryDirectory(prefix="cortex-hf-download-") as temporary:
        download_cache = Path(temporary)
        for pin in lock.models:
            fetched = Path(
                download(
                    repo_id=pin.repository,
                    revision=pin.revision,
                    cache_dir=download_cache,
                    allow_patterns=list(pin.required_files),
                )
            ).resolve()
            if fetched.name != pin.revision:
                raise ModelPayloadError(
                    f"Hugging Face resolved {pin.repository} to '{fetched.name}', "
                    f"expected '{pin.revision}'."
                )
            snapshot_target = output / pin.cache_name / "snapshots" / pin.revision
            shutil.copytree(fetched, snapshot_target, symlinks=False)
            refs = output / pin.cache_name / "refs"
            refs.mkdir(parents=True, exist_ok=True)
            (refs / "main").write_bytes(pin.revision.encode("ascii"))
    validate_snapshot_layout(output, lock)
    return output


def validate_snapshot_layout(snapshot_dir: Path, lock: ModelLock) -> None:
    """Require pinned refs and every FastEmbed runtime file before attestation."""
    root = Path(snapshot_dir).resolve()
    for pin in lock.models:
        model_root = root / pin.cache_name
        ref_path = model_root / "refs" / "main"
        try:
            ref = ref_path.read_text(encoding="ascii").strip()
        except (OSError, UnicodeError) as exc:
            raise ModelPayloadError(
                f"Snapshot ref is missing or unreadable for {pin.repository}: '{ref_path}'."
            ) from exc
        if ref != pin.revision:
            raise ModelPayloadError(
                f"Snapshot ref for {pin.repository} is '{ref}', expected '{pin.revision}'."
            )
        snapshot = model_root / "snapshots" / pin.revision
        for relative in pin.required_files:
            required = snapshot.joinpath(*relative.split("/"))
            if not required.is_file():
                raise ModelPayloadError(
                    f"Required model file is missing for {pin.repository}: '{relative}'."
                )


def _pin_for_role(lock: ModelLock, role: str) -> ModelPin:
    pin = next((candidate for candidate in lock.models if candidate.role == role), None)
    if pin is None:
        raise ModelPayloadError(f"Model lock has no '{role}' role.")
    return pin


def _validate_fastembed_registry(
    model_class: Any,
    pin: ModelPin,
) -> dict[str, Any]:
    supported = cast(list[dict[str, Any]], model_class.list_supported_models())
    model = next((item for item in supported if item.get("model") == pin.product_id), None)
    if model is None:
        raise ModelPayloadError(
            f"FastEmbed does not expose the pinned product ID '{pin.product_id}'."
        )
    sources = model.get("sources")
    if not isinstance(sources, dict) or sources.get("hf") != pin.repository:
        raise ModelPayloadError(
            f"FastEmbed source for '{pin.product_id}' does not match '{pin.repository}'."
        )
    model_file = model.get("model_file")
    additional_files = model.get("additional_files", [])
    if not isinstance(model_file, str) or not isinstance(additional_files, list):
        raise ModelPayloadError(
            f"FastEmbed registry entry for '{pin.product_id}' is incomplete."
        )
    expected_files = FASTEMBED_BASE_RUNTIME_FILES | {model_file} | set(additional_files)
    if set(pin.required_files) != expected_files:
        raise ModelPayloadError(
            f"models.lock runtime files for '{pin.product_id}' differ from FastEmbed: "
            f"expected {sorted(expected_files)}, got {sorted(pin.required_files)}."
        )
    return model


def run_offline_smoke(
    snapshot_dir: Path,
    proof_out: Path,
    *,
    lock_path: Path = DEFAULT_LOCK_PATH,
    embedding_class: Any | None = None,
    reranker_class: Any | None = None,
    installed_fastembed_version: str | None = None,
) -> tuple[int, int]:
    """Prove both pinned models can load and infer with networking disabled."""
    lock = load_lock(lock_path)
    root = Path(snapshot_dir).resolve()
    validate_snapshot_layout(root, lock)
    actual_version = (
        importlib.metadata.version("fastembed")
        if installed_fastembed_version is None
        else installed_fastembed_version
    )
    if actual_version != lock.fastembed_version:
        raise ModelPayloadError(
            f"Offline smoke requires FastEmbed {lock.fastembed_version}, got {actual_version}."
        )
    if embedding_class is None:
        from fastembed import TextEmbedding

        embedding_class = TextEmbedding
    if reranker_class is None:
        from fastembed.rerank.cross_encoder import TextCrossEncoder

        reranker_class = TextCrossEncoder

    embedding_pin = _pin_for_role(lock, "embedding")
    reranker_pin = _pin_for_role(lock, "reranker")
    embedding_registry = _validate_fastembed_registry(embedding_class, embedding_pin)
    _validate_fastembed_registry(reranker_class, reranker_pin)

    previous_offline = os.environ.get("HF_HUB_OFFLINE")
    os.environ["HF_HUB_OFFLINE"] = "1"
    network_error = ModelPayloadError(
        "Offline model smoke attempted to open a network connection."
    )
    try:
        with (
            patch.object(socket.socket, "connect", side_effect=network_error),
            patch.object(socket.socket, "connect_ex", side_effect=network_error),
            patch("socket.create_connection", side_effect=network_error),
        ):
            embedding = embedding_class(
                embedding_pin.product_id,
                cache_dir=str(root),
                local_files_only=True,
            )
            vectors = list(
                embedding.embed(["Cortex offline embedding inference smoke test."])
            )
            if len(vectors) != 1:
                raise ModelPayloadError(
                    f"Offline embedding smoke returned {len(vectors)} vectors, expected 1."
                )
            embedding_dimension = len(vectors[0])
            expected_dimension = embedding_registry.get("dim")
            if embedding_dimension != expected_dimension or not all(
                math.isfinite(float(value)) for value in vectors[0]
            ):
                raise ModelPayloadError(
                    "Offline embedding smoke returned an invalid vector: "
                    f"dimension={embedding_dimension}, expected={expected_dimension}."
                )

            reranker = reranker_class(
                reranker_pin.product_id,
                cache_dir=str(root),
                local_files_only=True,
            )
            scores = list(
                reranker.rerank(
                    "offline model payload",
                    [
                        "The embedded model payload is available locally.",
                        "This unrelated document is only a smoke-test candidate.",
                    ],
                )
            )
            if len(scores) != 2 or not all(math.isfinite(float(score)) for score in scores):
                raise ModelPayloadError(
                    f"Offline reranker smoke returned invalid scores: {scores!r}."
                )
    finally:
        if previous_offline is None:
            os.environ.pop("HF_HUB_OFFLINE", None)
        else:
            os.environ["HF_HUB_OFFLINE"] = previous_offline

    proof_path = Path(proof_out)
    proof_path.parent.mkdir(parents=True, exist_ok=True)
    proof_path.write_text(
        "\n".join(
            [
                "# Cortex offline model smoke test",
                "",
                "Result: **PASS**",
                "",
                f"- FastEmbed version: `{actual_version}`",
                "- `HF_HUB_OFFLINE=1` during loading and inference",
                "- `local_files_only=True` for embedding and reranker",
                "- Socket connect/connect_ex/create_connection blocked",
                f"- Embedding inference: one finite vector, dimension {embedding_dimension}",
                f"- Reranker inference: {len(scores)} finite scores",
                f"- Embedding revision: `{embedding_pin.revision}`",
                f"- Reranker revision: `{reranker_pin.revision}`",
                "",
                "The test instantiated both FastEmbed models from the pruned cache and ran",
                "real inference. Any missing runtime file or network attempt fails the job.",
            ]
        )
        + "\n",
        encoding="utf-8",
    )
    return embedding_dimension, len(scores)


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _payload_files(snapshot_dir: Path) -> list[Path]:
    root = Path(snapshot_dir).resolve()
    files = [path for path in root.rglob("*") if path.is_file()]
    return sorted(
        (path for path in files if path.resolve() != (root / MANIFEST_FILENAME).resolve()),
        key=lambda path: path.relative_to(root).as_posix(),
    )


def generate_attestation(
    snapshot_dir: Path,
    manifest_out: Path,
    inventory_out: Path,
    *,
    lock_path: Path = DEFAULT_LOCK_PATH,
) -> tuple[int, int]:
    """Generate the one-off manifest and human inventory for a pinned snapshot."""
    lock = load_lock(lock_path)
    root = Path(snapshot_dir).resolve()
    validate_snapshot_layout(root, lock)
    files = _payload_files(root)
    entries: dict[str, str] = {}
    sizes: dict[str, int] = {}
    for path in files:
        relative = path.relative_to(root).as_posix()
        entries[relative] = _sha256(path)
        sizes[relative] = path.stat().st_size
    total_bytes = sum(sizes.values())
    manifest = {
        "schema_version": 1,
        "runtime": {"fastembed_version": lock.fastembed_version},
        "models": [
            {
                "role": pin.role,
                "product_id": pin.product_id,
                "repository": pin.repository,
                "revision": pin.revision,
                "license": pin.license_id,
            }
            for pin in lock.models
        ],
        "totals": {"file_count": len(files), "bytes": total_bytes},
        "files": entries,
    }
    manifest_path = Path(manifest_out)
    manifest_path.parent.mkdir(parents=True, exist_ok=True)
    manifest_path.write_text(
        json.dumps(manifest, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    verify_manifest(root, manifest_path)

    inventory_path = Path(inventory_out)
    inventory_path.parent.mkdir(parents=True, exist_ok=True)
    lines = [
        "# Cortex embedded model inventory",
        "",
        "This attestation is generated once from the revisions pinned in `models.lock`.",
        f"It contains only the runtime files proven with FastEmbed {lock.fastembed_version}.",
        "Release builds verify a fresh fetch against the committed `manifest.json`; they",
        "do not regenerate the attestation.",
        "",
        "| Role | Product ID | Hugging Face repository | Revision | License |",
        "| --- | --- | --- | --- | --- |",
    ]
    for pin in lock.models:
        revision_url = f"https://huggingface.co/{pin.repository}/tree/{pin.revision}"
        lines.append(
            f"| {pin.role} | `{pin.product_id}` | `{pin.repository}` | "
            f"[`{pin.revision}`]({revision_url}) | `{pin.license_id}` |"
        )
    lines.extend(
        [
            "",
            f"Total payload: **{len(files)} files, {total_bytes} bytes "
            f"({total_bytes / (1024 * 1024):.2f} MiB)**.",
            "",
            "The license identifiers above come from the pinned Hugging Face model metadata.",
            "The Apache-2.0 text and model attributions are installed beside the payload.",
            "This binary-integrity manifest is separate from Cortex's vector contract in",
            "`embedding_fingerprint.py`.",
            "",
            "## Files",
            "",
            "| Path | Bytes | SHA-256 |",
            "| --- | ---: | --- |",
        ]
    )
    for relative, digest in entries.items():
        lines.append(f"| `{relative}` | {sizes[relative]} | `{digest}` |")
    inventory_path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return len(files), total_bytes


def _assert_manifest_matches_lock(manifest_path: Path, lock: ModelLock) -> None:
    try:
        raw: object = json.loads(Path(manifest_path).read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise ModelPayloadError(
            f"Could not read committed manifest '{manifest_path}': {exc}"
        ) from exc
    if not isinstance(raw, dict):
        raise ModelPayloadError("Committed model manifest must contain a JSON object.")
    manifest = cast(dict[str, Any], raw)
    manifest_runtime = manifest.get("runtime")
    if manifest_runtime != {"fastembed_version": lock.fastembed_version}:
        raise ModelPayloadError(
            "Committed model manifest FastEmbed runtime does not match models.lock."
        )
    manifest_models = manifest.get("models")
    expected = [
        {
            "role": pin.role,
            "product_id": pin.product_id,
            "repository": pin.repository,
            "revision": pin.revision,
            "license": pin.license_id,
        }
        for pin in lock.models
    ]
    if manifest_models != expected:
        raise ModelPayloadError(
            "Committed model manifest metadata does not match models.lock. "
            "Regenerate the one-off attestation and review it before release."
        )


def _materialize_declared_files(source: Path, output: Path, manifest_path: Path) -> None:
    for relative, _digest in manifest_entries(manifest_path):
        source_path = source.joinpath(*relative.split("/"))
        output_path = output.joinpath(*relative.split("/"))
        output_path.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(source_path, output_path)
    shutil.copy2(manifest_path, output / MANIFEST_FILENAME)


def prepare_payload(
    output_dir: Path,
    *,
    source_dir: Path | None = None,
    manifest_path: Path = DEFAULT_MANIFEST_PATH,
    lock_path: Path = DEFAULT_LOCK_PATH,
    environ: dict[str, str] | None = None,
    downloader: SnapshotDownloader | None = None,
) -> tuple[Path, int]:
    """Fetch or reuse a snapshot, verify it, and stage only attested files."""
    lock = load_lock(lock_path)
    committed_manifest = Path(manifest_path).resolve()
    if not committed_manifest.is_file():
        raise ModelPayloadError(
            f"Committed model manifest is missing: '{committed_manifest}'. Run and review "
            "the manual generation workflow before building a release."
        )
    _assert_manifest_matches_lock(committed_manifest, lock)
    values = os.environ if environ is None else environ
    configured_source = values.get(SNAPSHOT_ENV, "").strip()
    selected_source = source_dir or (Path(configured_source) if configured_source else None)
    output = _require_empty_directory(output_dir)

    if selected_source is not None:
        source = Path(selected_source).resolve()
        if source == output:
            raise ModelPayloadError(
                "Snapshot source and staged output must be different directories."
            )
        if not source.is_dir():
            raise ModelPayloadError(f"Model snapshot directory does not exist: '{source}'.")
        validate_snapshot_layout(source, lock)
        verify_manifest(source, committed_manifest)
        _materialize_declared_files(source, output, committed_manifest)
    else:
        with tempfile.TemporaryDirectory(prefix="cortex-model-source-") as temporary:
            source = fetch_models(
                Path(temporary) / "snapshot",
                lock_path=lock_path,
                downloader=downloader,
            )
            verify_manifest(source, committed_manifest)
            _materialize_declared_files(source, output, committed_manifest)

    verify_manifest(output)
    total_bytes = sum(path.stat().st_size for path in output.rglob("*") if path.is_file())
    return output, total_bytes


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--lock", type=Path, default=DEFAULT_LOCK_PATH)
    subparsers = parser.add_subparsers(dest="command", required=True)

    fetch = subparsers.add_parser("fetch", help="Fetch pinned FastEmbed runtime files.")
    fetch.add_argument("--output", type=Path, required=True)

    generate = subparsers.add_parser(
        "generate", help="Generate the one-off manifest and inventory."
    )
    generate.add_argument("--snapshot-dir", type=Path, required=True)
    generate.add_argument("--manifest-out", type=Path, required=True)
    generate.add_argument("--inventory-out", type=Path, required=True)

    smoke = subparsers.add_parser(
        "smoke", help="Load both models and run inference with networking blocked."
    )
    smoke.add_argument("--snapshot-dir", type=Path, required=True)
    smoke.add_argument("--proof-out", type=Path, required=True)

    verify = subparsers.add_parser("verify", help="Verify a snapshot against a manifest.")
    verify.add_argument("--snapshot-dir", type=Path, required=True)
    verify.add_argument("--manifest", type=Path, default=DEFAULT_MANIFEST_PATH)

    prepare = subparsers.add_parser(
        "prepare", help="Stage the verified payload used by the Windows installer."
    )
    prepare.add_argument("--output", type=Path, required=True)
    prepare.add_argument("--source", type=Path)
    prepare.add_argument("--manifest", type=Path, default=DEFAULT_MANIFEST_PATH)
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    """Run the selected payload operation."""
    args = _parser().parse_args(argv)
    lock_path = cast(Path, args.lock)
    if args.command == "fetch":
        output = fetch_models(cast(Path, args.output), lock_path=lock_path)
        print(f"Fetched pinned FastEmbed runtime files: {output}")
        return 0
    if args.command == "generate":
        file_count, total_bytes = generate_attestation(
            cast(Path, args.snapshot_dir),
            cast(Path, args.manifest_out),
            cast(Path, args.inventory_out),
            lock_path=lock_path,
        )
        print(f"Generated attestation for {file_count} files ({total_bytes} bytes).")
        return 0
    if args.command == "smoke":
        embedding_dimension, score_count = run_offline_smoke(
            cast(Path, args.snapshot_dir),
            cast(Path, args.proof_out),
            lock_path=lock_path,
        )
        print(
            "Offline model smoke passed: "
            f"embedding_dimension={embedding_dimension}, reranker_scores={score_count}."
        )
        return 0
    if args.command == "verify":
        lock = load_lock(lock_path)
        snapshot = cast(Path, args.snapshot_dir)
        manifest = cast(Path, args.manifest)
        _assert_manifest_matches_lock(manifest, lock)
        validate_snapshot_layout(snapshot, lock)
        verify_manifest(snapshot, manifest)
        print(f"Verified model snapshot against: {manifest.resolve()}")
        return 0
    output, total_bytes = prepare_payload(
        cast(Path, args.output),
        source_dir=cast(Path | None, args.source),
        manifest_path=cast(Path, args.manifest),
        lock_path=lock_path,
    )
    print(f"Prepared verified installer payload: {output} ({total_bytes} bytes).")
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
