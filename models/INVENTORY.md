# Cortex embedded model inventory

This attestation is generated once from the revisions pinned in `models.lock`.
It contains only the runtime files proven with FastEmbed 0.8.0.
Release builds verify a fresh fetch against the committed `manifest.json`; they
do not regenerate the attestation.

| Role | Product ID | Hugging Face repository | Revision | License |
| --- | --- | --- | --- | --- |
| embedding | `sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2` | `qdrant/paraphrase-multilingual-MiniLM-L12-v2-onnx-Q` | [`faf4aa4225822f3bc6376869cb1164e8e3feedd0`](https://huggingface.co/qdrant/paraphrase-multilingual-MiniLM-L12-v2-onnx-Q/tree/faf4aa4225822f3bc6376869cb1164e8e3feedd0) | `apache-2.0` |
| reranker | `jinaai/jina-reranker-v1-tiny-en` | `jinaai/jina-reranker-v1-tiny-en` | [`aca45de6945b5dc6399abcd2a9c55ded5dc9111f`](https://huggingface.co/jinaai/jina-reranker-v1-tiny-en/tree/aca45de6945b5dc6399abcd2a9c55ded5dc9111f) | `apache-2.0` |

Total payload: **12 files, 386522634 bytes (368.62 MiB)**.

The license identifiers above come from the pinned Hugging Face model metadata.
The Apache-2.0 text and model attributions are installed beside the payload.
This binary-integrity manifest is separate from Cortex's vector contract in
`embedding_fingerprint.py`.

## Files

| Path | Bytes | SHA-256 |
| --- | ---: | --- |
| `models--jinaai--jina-reranker-v1-tiny-en/refs/main` | 40 | `6d12d1848583316c62c537b84e7b4743dbc95490f750763747d1e1abd98b751d` |
| `models--jinaai--jina-reranker-v1-tiny-en/snapshots/aca45de6945b5dc6399abcd2a9c55ded5dc9111f/config.json` | 1206 | `dc70646aa6c9e75e3c513cc9c037f35ad54308001c3961d45c0f69749bcfb022` |
| `models--jinaai--jina-reranker-v1-tiny-en/snapshots/aca45de6945b5dc6399abcd2a9c55ded5dc9111f/onnx/model.onnx` | 132350375 | `e0e743251c7566e2b1e4f5ad091c681a700d7d7a3d85541ea56ca3acf43d1afa` |
| `models--jinaai--jina-reranker-v1-tiny-en/snapshots/aca45de6945b5dc6399abcd2a9c55ded5dc9111f/special_tokens_map.json` | 280 | `06e405a36dfe4b9604f484f6a1e619af1a7f7d09e34a8555eb0b77b66318067f` |
| `models--jinaai--jina-reranker-v1-tiny-en/snapshots/aca45de6945b5dc6399abcd2a9c55ded5dc9111f/tokenizer.json` | 2030772 | `0046da43cc8c424b317f56b092b0512aaaa65c4f925d2f16af9d9eeb4d0ef902` |
| `models--jinaai--jina-reranker-v1-tiny-en/snapshots/aca45de6945b5dc6399abcd2a9c55ded5dc9111f/tokenizer_config.json` | 1215 | `d291c6652d96d56ffdbcf1ea19d9bae5ed79003f7648c627e725a619227ce8fa` |
| `models--qdrant--paraphrase-multilingual-MiniLM-L12-v2-onnx-Q/refs/main` | 40 | `f5719ccbb70b50cf31f07542d53c3f498e8ee4f420527130b74c666f8dd80860` |
| `models--qdrant--paraphrase-multilingual-MiniLM-L12-v2-onnx-Q/snapshots/faf4aa4225822f3bc6376869cb1164e8e3feedd0/config.json` | 673 | `c8ec081fdad2df991bf5abbf18418fec7a5cdaa421f60ffb060a30040b8c376f` |
| `models--qdrant--paraphrase-multilingual-MiniLM-L12-v2-onnx-Q/snapshots/faf4aa4225822f3bc6376869cb1164e8e3feedd0/model_optimized.onnx` | 235052644 | `634d0f66c29dc934c8fa72b8a4fe91dd4d420a22f1d82a241058d4316e659a99` |
| `models--qdrant--paraphrase-multilingual-MiniLM-L12-v2-onnx-Q/snapshots/faf4aa4225822f3bc6376869cb1164e8e3feedd0/special_tokens_map.json` | 964 | `8c785abebea9ae3257b61681b4e6fd8365ceafde980c21970d001e834cf10835` |
| `models--qdrant--paraphrase-multilingual-MiniLM-L12-v2-onnx-Q/snapshots/faf4aa4225822f3bc6376869cb1164e8e3feedd0/tokenizer.json` | 17083009 | `fa685fc160bbdbab64058d4fc91b60e62d207e8dc60b9af5c002c5ab946ded00` |
| `models--qdrant--paraphrase-multilingual-MiniLM-L12-v2-onnx-Q/snapshots/faf4aa4225822f3bc6376869cb1164e8e3feedd0/tokenizer_config.json` | 1416 | `0666eebf692422757e1dddf3c9fb1ded73ba3dc726c5828671fc89e45bf3609f` |
