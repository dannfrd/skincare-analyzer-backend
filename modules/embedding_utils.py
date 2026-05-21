import warnings
from typing import List

# Suppress HuggingFace/PyTorch warnings during load
with warnings.catch_warnings():
    warnings.simplefilter("ignore")
    from sentence_transformers import SentenceTransformer

# Initialize the model lazily
_model = None

def _get_model():
    global _model
    if _model is None:
        print("Loading local embedding model (all-MiniLM-L6-v2)...")
        # Load a small and fast local model for semantic search
        _model = SentenceTransformer('all-MiniLM-L6-v2')
    return _model

def get_embedding(text: str) -> List[float]:
    """Generate a vector embedding using a local SentenceTransformer model."""
    try:
        model = _get_model()
        # Encode text to vector and convert to flat list of floats
        vector = model.encode(text).tolist()
        return vector
    except Exception as e:
        print(f"Error generating embedding locally: {e}")
        # fallback to zero vector to prevent hard crash
        return [0.0] * 384
