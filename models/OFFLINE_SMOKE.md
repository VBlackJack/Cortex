# Cortex offline model smoke test

Result: **PASS**

- FastEmbed version: `0.8.0`
- `HF_HUB_OFFLINE=1` during loading and inference
- `local_files_only=True` for embedding and reranker
- Socket connect/connect_ex/create_connection blocked
- Embedding inference: one finite vector, dimension 384
- Reranker inference: 2 finite scores
- Embedding revision: `faf4aa4225822f3bc6376869cb1164e8e3feedd0`
- Reranker revision: `aca45de6945b5dc6399abcd2a9c55ded5dc9111f`

The test instantiated both FastEmbed models from the pruned cache and ran
real inference. Any missing runtime file or network attempt fails the job.
