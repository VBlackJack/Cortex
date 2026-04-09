"""
Cortex — Configuration

Both KB_PATH and CHROMA_PATH are environment-driven for portability:
  - CORTEX_KB_PATH      : root of the markdown knowledge base (REQUIRED for indexing)
  - CORTEX_CHROMA_PATH  : vector database location (defaults next to this script)

Search keeps working without CORTEX_KB_PATH (read-only against an existing index).
Only `cortex_sync` / indexer.sync() require it.
"""

import os
from pathlib import Path

# Cortex install directory — derived from this file's location.
# Lets the whole project relocate without editing any code.
SCRIPT_DIR = Path(__file__).parent.resolve()

# Knowledge base root — must be set via env var when indexing.
# Empty string when unset; consumers (indexer.sync) validate explicitly.
KB_PATH = os.environ.get("CORTEX_KB_PATH", "")

# ChromaDB persistent storage — defaults next to the code so a fresh clone
# works without configuration. Override via CORTEX_CHROMA_PATH if you want
# the vector database on a different drive.
CHROMA_PATH = os.environ.get("CORTEX_CHROMA_PATH", str(SCRIPT_DIR / "chroma_db"))

# ChromaDB collection name
COLLECTION_NAME = "cortex"

# Multilingual embedding model via fastembed (ONNX — no PyTorch, low RAM)
# Handles French + English content natively
EMBEDDING_MODEL = "sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2"

# Chunking parameters
# Model `paraphrase-multilingual-MiniLM-L12-v2` truncates input at 128 tokens.
# We size chunks in characters and stay conservatively under that cap.
# Assuming ~3.5 chars/token for French, 400 chars ≈ 110-115 tokens.
CHUNK_CHARS = 400
CHUNK_OVERLAP_CHARS = 60

# Search defaults
TOP_K_DEFAULT = 5

# Directories and files to skip during indexing.
# Applied at every depth, including the section level (first-level dirs).
EXCLUDE_DIRS = {"_attachments", "zzz_Corbeille"}
EXCLUDE_FILES = {"00_INDEX.md"}

# Sections are auto-discovered at runtime: every first-level directory under
# CORTEX_KB_PATH that is not in EXCLUDE_DIRS becomes a section. See
# `indexer.discover_sections()`.
