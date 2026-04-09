"""
Cortex — Configuration
"""

# Knowledge base root (Confluence markdown export)
KB_PATH = r"G:\_DATA"

# ChromaDB persistent storage
CHROMA_PATH = r"G:\_dev\Cortex\chroma_db"

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

# Directories and files to skip during indexing
EXCLUDE_DIRS = {"_attachments", "zzz_Corbeille"}
EXCLUDE_FILES = {"00_INDEX.md"}

# Known sections (first-level directories in KB_PATH)
KNOWN_SECTIONS = [
    "Adsec",
    "Ansible",
    "Processes",
    "Products",
    "Projects",
    "Technical Services",
    "Zabbix",
]
