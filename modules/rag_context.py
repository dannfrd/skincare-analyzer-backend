import os
import re
from typing import Any, Dict, List, Tuple

from qdrant_client import QdrantClient
from qdrant_client.models import FieldCondition, Filter, MatchValue
from modules.embedding_utils import get_embedding, get_embeddings_batch

# Qdrant Database Path
QDRANT_DATA_DIR = os.path.join(
    os.path.dirname(os.path.dirname(__file__)),
    "qdrant_data"
)
COLLECTION_NAME = "skincare_ingredients"


def _normalize_name(value: str) -> str:
    normalized = re.sub(r"[^A-Za-z0-9\s\-\+\./]", " ", value.upper())
    return re.sub(r"\s+", " ", normalized).strip()

# Initialize client lazily or on module load
try:
    _qdrant_client = QdrantClient(path=QDRANT_DATA_DIR)
    # check if collection exists
    if not _qdrant_client.collection_exists(COLLECTION_NAME):
        print(f"Warning: Qdrant collection '{COLLECTION_NAME}' does not exist. Run qdrant_setup.py first.")
        _qdrant_client = None
except Exception as e:
    print(f"Error initializing Qdrant client: {e}")
    _qdrant_client = None


def _clip(value: str, max_len: int = 220) -> str:
    """Clip text to max length"""
    compact = re.sub(r"\s+", " ", value or "").strip()
    if len(compact) <= max_len:
        return compact
    return compact[: max_len - 3].rstrip() + "..."


def get_ingredient_simple_description(ingredient_name: str) -> Dict[str, Any]:
    """
    Get simple description for a single ingredient from Qdrant.
    """
    if not ingredient_name or not ingredient_name.strip() or not _qdrant_client:
        return {}
        
    try:
        normalized_name = _normalize_name(ingredient_name)
        exact_matches, _ = _qdrant_client.scroll(
            collection_name=COLLECTION_NAME,
            scroll_filter=Filter(
                must=[
                    FieldCondition(
                        key="normalized_name",
                        match=MatchValue(value=normalized_name),
                    )
                ]
            ),
            limit=1,
            with_payload=True,
            with_vectors=False,
        )

        if exact_matches:
            payload = exact_matches[0].payload or {}
            score = 1.0
        else:
            vector = get_embedding(ingredient_name)
            search_result = _qdrant_client.search(
                collection_name=COLLECTION_NAME,
                query_vector=vector,
                limit=1
            )
            if not search_result:
                return {}

            best_hit = search_result[0]
            if best_hit.score < 0.55:
                return {}

            payload = best_hit.payload or {}
            score = best_hit.score

            # Avoid assigning metadata from a semantically similar but different ingredient.
            if _normalize_name(str(payload.get("name") or "")) != normalized_name:
                return {}

        if not payload:
            return {}
            
        # Extract simple description (first 200 chars of full description)
        full_desc = payload.get("description", "")
        if full_desc:
            sentences = full_desc.split(". ")
            if sentences:
                simple_desc = sentences[0] + "."
                if len(simple_desc) > 200:
                    simple_desc = simple_desc[:197] + "..."
            else:
                simple_desc = full_desc[:197] + "..." if len(full_desc) > 200 else full_desc
        else:
            simple_desc = ""
            
        return {
            "name": payload.get("name", ingredient_name),
            "simple_description": simple_desc,
            "functions": payload.get("functions", ""),
            "warnings": payload.get("warnings", ""),
            "origin": payload.get("origin", ""),
            "harmful": payload.get("harmful", False),
            "bpom_warning": payload.get("bpom_warning", ""),
            "rating": payload.get("rating", ""),
            "found_in_products": payload.get("found_in_products", []),
            "sources": payload.get("sources", []),
            "found_in_dataset": True,
            "score": score
        }
    except Exception as e:
        print(f"Error querying Qdrant for {ingredient_name}: {e}")
        return {}


def build_rag_context(
    ingredient_tokens: List[str],
    top_k: int | None = None,
) -> Tuple[str, Dict[str, Any]]:
    """
    Build RAG context from Qdrant Local Database.
    """
    cleaned_tokens = [token.strip() for token in ingredient_tokens if token and token.strip()]
    if not cleaned_tokens:
        return "", {"enabled": False, "reason": "empty_tokens", "items": []}
        
    if not _qdrant_client:
        return "", {"enabled": False, "reason": "qdrant_client_unavailable", "items": []}

    max_items = top_k or int(os.getenv("RAG_MAX_CONTEXT_ITEMS", "12"))
    
    selected_items: List[Dict[str, Any]] = []
    seen_names = set()

    # Batch embedding generation for all tokens at once
    try:
        vectors = get_embeddings_batch(cleaned_tokens)
    except Exception as e:
        print(f"Error generating batch embeddings in build_rag_context: {e}")
        vectors = [[0.0] * 384 for _ in cleaned_tokens]

    for i, token in enumerate(cleaned_tokens):
        try:
            vector = vectors[i]
            search_result = _qdrant_client.search(
                collection_name=COLLECTION_NAME,
                query_vector=vector,
                limit=1
            )
            
            if not search_result:
                continue
                
            best_hit = search_result[0]
            # Threshold to prevent bad semantic matches
            if best_hit.score < 0.55:
                continue
                
            payload = best_hit.payload
            if not payload:
                continue
                
            name = payload.get("name", "")
            
            if name.upper() in seen_names:
                continue
                
            seen_names.add(name.upper())
            
            item_data = dict(payload)
            item_data["token"] = token
            item_data["match_type"] = f"semantic (score: {best_hit.score:.2f})"
            selected_items.append(item_data)
            
            if len(selected_items) >= max_items:
                break
        except Exception as e:
            print(f"Error querying token {token}: {e}")
            continue

    if not selected_items:
        return "", {
            "enabled": True,
            "reason": "no_retrieval_match",
            "items": [],
        }

    # Build context string
    lines = ["Dataset context (Semantic Search Qdrant):"]
    
    for index, item in enumerate(selected_items, start=1):
        parts = []
        
        if item.get("rating"):
            parts.append(f"rating: {item['rating']}")
            
        if item.get("description"):
            parts.append(f"deskripsi: {_clip(item['description'], 180)}")
        
        if item.get("functions"):
            parts.append(f"fungsi: {item['functions']}")
        
        if item.get("warnings"):
            parts.append(f"⚠️ peringatan: {item['warnings']}")
        
        if item.get("origin"):
            parts.append(f"asal: {item['origin']}")
        
        if item.get("harmful"):
            parts.append(f"🚨 BPOM: BAHAN BERBAHAYA/DILARANG")
            
        if item.get("found_in_products"):
            products_str = ", ".join(item["found_in_products"])
            parts.append(f"contoh produk: {products_str}")
        
        sources_str = ", ".join(item.get("sources", []))
        
        context_payload = " | ".join(parts) if parts else "data terbatas"
        lines.append(
            f"{index}. {item['name']} ({item['match_type']}) [{sources_str}]: {context_payload}"
        )

    return "\n".join(lines), {
        "enabled": True,
        "reason": "ok",
        "items": selected_items,
    }
