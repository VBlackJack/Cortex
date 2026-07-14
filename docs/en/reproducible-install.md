# Reproducible install

[Francais](../fr/install-reproductible.md) | **English**

[Back to table of contents](index.md)

## Two files, two roles

Cortex separates two levels of dependency pinning:

| File | Scope | Use |
|---|---|---|
| `requirements.txt` | The direct dependencies (6), pinned to exact versions | Single source read by `pyproject.toml`; standard install |
| `requirements.lock` | The full transitive tree, hash-locked | Reproducible install and supply-chain audit |

`requirements.txt` pins the versions of the packages Cortex imports directly but
lets pip resolve their own dependencies freely. `requirements.lock` additionally
pins the entire transitive tree and attaches each package's SHA-256 hashes,
which makes the install byte-for-byte identical and silently refuses any
substituted artifact.

The lock is universal (cross-platform): a single file covers Windows, Linux and
macOS through environment markers. It captures the conditional branches a
single-platform lock would miss, for example `pywin32` and `colorama` on Windows
only, or the `numpy` and `onnxruntime` variants that depend on the Python
version.

## Install with hash locking

```powershell
pip install --require-hashes -r requirements.lock
```

With `--require-hashes`, pip refuses to install any package whose archive does
not match a hash present in the lock, and requires every dependency to be
pinned. This is the mode to use for a reproducible install (production machine,
CI, audit).

Dry run, without installing anything:

```powershell
pip install --require-hashes --dry-run -r requirements.lock
```

The standard install described in [Setup](setup.md) remains valid for everyday
use; the lock is the strict mode, not a mandatory replacement.

## Regenerate the lock when requirements.txt changes

As soon as `requirements.txt` changes (bumping a dependency, adding, removing),
`requirements.lock` must be regenerated, otherwise the two drift apart. The
exact command is in the header of `requirements.lock`:

```powershell
uv pip compile --universal --generate-hashes --python-version 3.10 requirements.txt -o requirements.lock
```

Things to watch:

- `uv` is used only to generate the lock (development tool). The installer stays
  `pip`: neither the standard install nor CI needs `uv`.
- `--universal` produces the single cross-platform file; do not drop it,
  otherwise the lock becomes specific to the generating platform.
- `--python-version 3.10` targets the minimum supported version, which
  guarantees the lock stays valid across the whole 3.10 to 3.12 matrix.
- Commit `requirements.lock` together with the matching `requirements.txt` in
  the same commit.

## Supply-chain audit in CI

The CI `dependency-audit` job runs `pip-audit` on `requirements.lock`, so on the
full transitive tree rather than the direct dependencies alone. This maximizes
coverage for known vulnerabilities. One vulnerability is explicitly ignored and
documented in the workflow (`PYSEC-2026-311`, the ChromaDB HTTP server path that
Cortex never uses, see [Security](security.md)); any other vulnerability fails
the job.
