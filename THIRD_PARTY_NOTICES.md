# Third-party notices

The Cortex Windows installer redistributes the following unmodified model artifacts.
The complete Apache License, Version 2.0 text is installed as
`models/licenses/Apache-2.0.txt` beside these artifacts.

## Multilingual MiniLM embedding model

- Product ID: `sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2`
- ONNX repository: `qdrant/paraphrase-multilingual-MiniLM-L12-v2-onnx-Q`
- Source: https://huggingface.co/qdrant/paraphrase-multilingual-MiniLM-L12-v2-onnx-Q
- Revision: `faf4aa4225822f3bc6376869cb1164e8e3feedd0`
- License: Apache-2.0

## Jina reranker

- Product ID: `jinaai/jina-reranker-v1-tiny-en`
- Repository: `jinaai/jina-reranker-v1-tiny-en`
- Source: https://huggingface.co/jinaai/jina-reranker-v1-tiny-en
- Revision: `aca45de6945b5dc6399abcd2a9c55ded5dc9111f`
- License: Apache-2.0

The pinned source repositories and binary SHA-256 values are documented in
`models/INVENTORY.md` and `models/manifest.json` in the Cortex source distribution.

## Runtime dependencies

This file covers the two embedded models only. The licenses of every runtime
dependency bundled in the standalone executable ship as the generated
`THIRD_PARTY_LICENSES.json`, with the license texts it lists, in the `licenses`
folder next to the executable (in the installation folder and in each portable
archive). `packaging/license_bundle.py` produces that inventory from the exact
PyInstaller build and verifies it at build time, so a release cannot ship a bundled
dependency without its license.
