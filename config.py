# Copyright 2026 Julien Bombled
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.

import os
from pathlib import Path

_SCRIPT_DIR = Path(__file__).parent.resolve()

KB_PATH = os.environ.get("CORTEX_KB_PATH", r"G:\_DATA").strip('"')
CHROMA_PATH = str(_SCRIPT_DIR / "chroma_db")
COLLECTION_NAME = "cortex"
EMBEDDING_MODEL = "sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2"

# Chunk sizes (characters)
CHUNK_SIZE = 512
CHUNK_OVERLAP = 64
MAX_MARKDOWN_FILE_SIZE_BYTES = int(os.environ.get("CORTEX_MAX_MARKDOWN_FILE_SIZE_BYTES", "1000000"))

EXCLUDE_DIRS = {"_attachments", "zzz_Corbeille"}
EXCLUDE_FILES = {"00_INDEX.md"}

FRESHNESS_CONTRACT_ID = "freshness-contract-v1"
FRESHNESS_CONTRACT_VERSION = "v1"
FRESHNESS_EXCLUDED_DIRS = frozenset({".datacron", "_archive", "_trash"})

KNOWN_SECTIONS = [
    "Adsec",
    "Ansible",
    "Processes",
    "Products",
    "Projects",
    "Technical Services",
    "Zabbix",
    "Books",  # ebooks and reference PDFs - place files in G:\_DATA\Books\
]
