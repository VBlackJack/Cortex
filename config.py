KB_PATH         = r"G:\_DATA"
CHROMA_PATH     = r"G:\_dev\Cortex\chroma_db"
COLLECTION_NAME = "cortex"
EMBEDDING_MODEL = "sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2"

# Chunk sizes - both naming conventions supported
CHUNK_SIZE         = 512
CHUNK_OVERLAP      = 64
CHUNK_CHARS        = CHUNK_SIZE         # alias used by chunker.py
CHUNK_OVERLAP_CHARS = CHUNK_OVERLAP     # alias used by chunker.py

EXCLUDE_DIRS  = {"_attachments", "zzz_Corbeille"}
EXCLUDE_FILES = {"00_INDEX.md"}

KNOWN_SECTIONS = [
    "Adsec",
    "Ansible",
    "Processes",
    "Products",
    "Projects",
    "Technical Services",
    "Zabbix",
    "Books",       # ebooks and reference PDFs - place files in G:\_DATA\Books\
]
