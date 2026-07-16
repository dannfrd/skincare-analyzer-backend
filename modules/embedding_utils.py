import warnings
import os
import requests
import numpy as np
from typing import List

# Mencegah HuggingFace Hub melakukan request telemetry/cek online yang tidak perlu
os.environ["HF_HUB_DISABLE_TELEMETRY"] = "1"
os.environ["HF_HUB_DISABLE_SYMLINKS_WARNING"] = "1"

# Suppress HuggingFace/PyTorch warnings during load
with warnings.catch_warnings():
    warnings.simplefilter("ignore")
    from sentence_transformers import SentenceTransformer

# Initialize the model lazily
_model = None

def _get_embedding_from_api(texts: List[str]) -> List[List[float]] | None:
    """Mengambil embedding menggunakan Hugging Face Serverless Inference API (Paling cepat & 0MB RAM lokal)."""
    token = os.getenv("HF_TOKEN") or os.getenv("HF_API_KEY")
    headers = {"Authorization": f"Bearer {token}"} if token else {}
    
    # URL Endpoint resmi Serverless Feature Extraction
    API_URL = "https://api-inference.huggingface.co/models/BAAI/bge-small-en-v1.5"
    
    try:
        response = requests.post(
            API_URL,
            headers=headers,
            json={"inputs": texts, "options": {"wait_for_model": True}},
            timeout=8
        )
        if response.status_code == 200:
            res_json = response.json()
            if isinstance(res_json, list) and len(res_json) > 0:
                normalized_embeddings = []
                for emb in res_json:
                    # Normalisasi vektor agar cocok dengan cosine similarity RAG
                    if isinstance(emb, list):
                        arr = np.array(emb, dtype=np.float32)
                        norm = np.linalg.norm(arr)
                        if norm > 0:
                            arr = arr / norm
                        normalized_embeddings.append(arr.tolist())
                    else:
                        return None
                return normalized_embeddings
    except Exception as e:
        print(f"HF Inference API connection info (offline/timeout): {e}")
    return None

def _get_model():
    global _model
    if _model is None:
        project_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        local_path = os.path.join(project_root, "model_bge")
        print("Memuat local embedding model...")
        
        # 1. Coba load dari folder proyek 'model_bge' yang sudah berhasil didownload penuh
        try:
            if os.path.exists(local_path):
                _model = SentenceTransformer(local_path)
                print("✓ Embedding model berhasil dimuat dari folder lokal proyek 'model_bge'.")
                return _model
        except Exception as e_local:
            print(f"Gagal memuat dari folder lokal 'model_bge' ({e_local}). Mencoba cache HuggingFace...")

        # 2. Coba load dari cache global Hugging Face (.cache/huggingface/hub)
        model_name = os.getenv("EMBEDDING_MODEL", "BAAI/bge-small-en-v1.5")
        try:
            _model = SentenceTransformer(model_name, local_files_only=True)
            print(f"✓ Embedding model '{model_name}' dimuat dari cache global.")
        except Exception:
            try:
                # Coba download dari internet jika belum ada di cache
                import huggingface_hub.constants
                huggingface_hub.constants.HF_ENDPOINT = "https://huggingface.co"
                if "HF_ENDPOINT" in os.environ:
                    del os.environ["HF_ENDPOINT"]
                _model = SentenceTransformer(model_name, local_files_only=False)
                print(f"✓ Berhasil mengunduh '{model_name}' dari Hugging Face.")
            except Exception:
                # 3. AUTO-FALLBACK: Jika offline total, muat model 'all-MiniLM-L6-v2' dari cache
                print("🔄 AUTO-FALLBACK: Memuat model 'all-MiniLM-L6-v2' dari cache lokal...")
                _model = SentenceTransformer('all-MiniLM-L6-v2', local_files_only=True)
                print("✓ Auto-Fallback berhasil!")
    return _model

def get_embedding(text: str) -> List[float]:
    """Generate a vector embedding using HF Inference API, falling back to local BAAI or all-MiniLM models."""
    try:
        # Coba ambil via Serverless API terlebih dahulu (sangat cepat & hemat RAM)
        api_res = _get_embedding_from_api([text])
        if api_res and len(api_res) > 0:
            return api_res[0]
            
        # Fallback ke model lokal jika API gagal/offline
        model = _get_model()
        vector = model.encode(text, normalize_embeddings=True).tolist()
        return vector
    except Exception as e:
        print(f"Error generating embedding: {e}")
        return [0.0] * 384

def get_embeddings_batch(texts: List[str]) -> List[List[float]]:
    """Generate batch vector embeddings using HF Inference API, falling back to local models."""
    if not texts:
        return []
    try:
        # Coba ambil via Serverless API terlebih dahulu
        api_res = _get_embedding_from_api(texts)
        if api_res:
            return api_res
            
        # Fallback ke model lokal jika API gagal/offline
        model = _get_model()
        vectors = model.encode(texts, normalize_embeddings=True).tolist()
        return vectors
    except Exception as e:
        print(f"Error generating batch embeddings: {e}")
        return [[0.0] * 384 for _ in texts]

