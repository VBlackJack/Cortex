# Embedded model attestation

This directory contains only the small, reviewed attestation for Cortex's embedded
FastEmbed payload. Model weights and cache snapshots must never be committed.

`manifest.json`, `INVENTORY.md`, and `OFFLINE_SMOKE.md` are generated once by the manual
`generate-model-manifest.yml` workflow, reviewed, and committed. The payload contains
only the files loaded by FastEmbed 0.8.0. The workflow proves that set with real offline
embedding and reranker inference before it emits the attestation. Release builds fetch a
fresh runtime snapshot at the revisions in `models.lock` and verify it against the
committed manifest. A release build never regenerates its own manifest.

For a local build without Hugging Face access, set `CORTEX_MODEL_SNAPSHOT_DIR` to a
previously materialized cache root. `scripts/model_payload.py prepare` still verifies it
against the committed manifest before it can enter the installer.

On Windows, after building `dist/cortex.exe`, the local fallback is:

```powershell
$env:CORTEX_MODEL_SNAPSHOT_DIR = "D:\cortex-model-snapshot"
python scripts/model_payload.py prepare --output build/model-payload
$version = (python -c "from _version import __version__; print(__version__)").Trim()
& "$env:ProgramFiles(x86)\Inno Setup 6\ISCC.exe" `
  "/DAppVersion=$version" `
  "/DModelPayloadDir=$((Resolve-Path build/model-payload).Path)" `
  packaging\windows\cortex-installer.iss
```

The fallback does not generate or modify the committed manifest and never needs network
access.
