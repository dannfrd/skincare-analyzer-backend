import warnings
import os
from typing import List

# Mencegah HuggingFace Hub melakukan request telemetry/cek online yang tidak perlu
os.environ["HF_HUB_DISABLE_TELEMETRY"] = "1"
os.environ["HF_HUB_DISABLE_SYMLINKS_WARNING"] = "1"

# Gunakan CDN Mirror Resmi (hf-mirror.com) jika server utama Hugging Face (huggingface.co) mengalami 504 CloudFront Timeout
if "HF_ENDPOINT" not in os.environ:
    os.environ["HF_ENDPOINT"] = "https://hf-mirror.com"

# Suppress HuggingFace/PyTorch warnings during load
with warnings.catch_warnings():
    warnings.simplefilter("ignore")
    from sentence_transformers import SentenceTransformer

# Initialize the model lazily
_model = None

def _get_model():
    global _model
    if _model is None:
        model_name = os.getenv("EMBEDDING_MODEL", "BAAI/bge-small-en-v1.5")
        print(f"Loading local embedding model ({model_name})...")
        try:
            # 1. Coba load dari cache lokal terlebih dahulu agar tidak terhambat koneksi/timeout server HF (HTTP 504)
            _model = SentenceTransformer(model_name, local_files_only=True)
            print(f"✓ Embedding model '{model_name}' loaded instantly from local cache.")
        except Exception:
            # 2. Jika belum ada di cache, unduh dari Hugging Face / Mirror
            print(f"Model '{model_name}' belum ada di cache lokal. Mengunduh dari Hugging Face...")
            try:
                _model = SentenceTransformer(model_name, local_files_only=False)
            except Exception as download_error:
                # 3. AUTO-FALLBACK: Jika HuggingFace down/504 Timeout, langsung gunakan model 'all-MiniLM-L6-v2' yang SUDAH ADA di cache PC Anda!
                print(f"⚠️ Gagal mengunduh '{model_name}' (Server HuggingFace Timeout/504 Offline).")
                print("🔄 AUTO-FALLBACK: Memuat model 'all-MiniLM-L6-v2' dari cache lokal yang sudah tersedia di PC Anda...")
                _model = SentenceTransformer('all-MiniLM-L6-v2', local_files_only=True)
                print("✓ Auto-Fallback berhasil! Backend aktif dengan 'all-MiniLM-L6-v2' (offline cache).")
    return _model

def get_embedding(text: str) -> List[float]:
    """Generate a vector embedding using a local SentenceTransformer model (SOTA BAAI/bge-small-en-v1.5)."""
    try:
        model = _get_model()
        # Encode text to unit-normalized vector for optimal cosine similarity matching
        vector = model.encode(text, normalize_embeddings=True).tolist()
        return vector
    except Exception as e:
        print(f"Error generating embedding locally: {e}")
        # fallback to zero vector to prevent hard crash
        return [0.0] * 384

def get_embeddings_batch(texts: List[str]) -> List[List[float]]:
    """Generate vector embeddings in batch using a local SentenceTransformer model (SOTA BAAI/bge-small-en-v1.5)."""
    if not texts:
        return []
    try:
        model = _get_model()
        # Encode texts to unit-normalized vectors
        vectors = model.encode(texts, normalize_embeddings=True).tolist()
        return vectors
    except Exception as e:
        print(f"Error generating batch embeddings locally: {e}")
        # fallback to zero vectors to prevent hard crash
        return [[0.0] * 384 for _ in texts]

