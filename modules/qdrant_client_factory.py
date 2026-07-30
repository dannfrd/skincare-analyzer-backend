"""
Factory untuk membuat QdrantClient yang mendukung dua mode:

1. Server mode  (QDRANT_URL env var tersedia, mis. http://localhost:6333)
   → Digunakan di production/VPS via Docker Compose
   → Mendukung akses concurrent (backend + ingest script sekaligus)

2. File-local mode  (fallback jika QDRANT_URL tidak ada)
   → Digunakan saat development lokal tanpa Docker
   → TIDAK bisa concurrent — hanya satu proses yang bisa akses

Set env var untuk memilih mode:
    export QDRANT_URL=http://localhost:6333    # server mode
    # (tidak di-set)                           # file-local mode
"""

import os
from qdrant_client import QdrantClient

QDRANT_DATA_DIR = os.path.join(
    os.path.dirname(os.path.dirname(__file__)),
    "qdrant_data",
)

COLLECTION_NAME = "skincare_ingredients"
VECTOR_SIZE = 384  # BAAI/bge-small-en-v1.5 (SOTA 384-dim drop-in upgrade) or all-MiniLM-L6-v2


def get_qdrant_client() -> QdrantClient:
    """
    Buat QdrantClient berdasarkan env var QDRANT_URL.

    Server mode  → QdrantClient(url=QDRANT_URL)
    File mode    → QdrantClient(path=QDRANT_DATA_DIR)
    """
    qdrant_url = os.getenv("QDRANT_URL", "").strip()
    if qdrant_url:
        return QdrantClient(url=qdrant_url)
    else:
        os.makedirs(QDRANT_DATA_DIR, exist_ok=True)
        return QdrantClient(path=QDRANT_DATA_DIR)


def get_qdrant_mode() -> str:
    """Kembalikan string mode yang sedang dipakai."""
    qdrant_url = os.getenv("QDRANT_URL", "").strip()
    return f"server ({qdrant_url})" if qdrant_url else f"file-local ({QDRANT_DATA_DIR})"
