"""
Product Recommender module using dual-strategy semantic similarity.

Strategy 1 (Semantic via Qdrant):
  - Embed each scanned ingredient name
  - Search Qdrant for semantically similar ingredients (cosine similarity)
  - Collect related_product_ids from matching payloads
  - Score products by how many scanned ingredients they share (semantically)

Strategy 2 (String-overlap fallback):
  - Classic substring overlap against ingredient_raw
  - Used when Qdrant is unavailable or returns < min_results

CATATAN PENTING (file-local mode):
  Qdrant file-local client HARUS ditutup (client.close()) setelah setiap
  operasi agar tidak ada file lock yang tersisa. Jika ada lock yang tidak
  dilepas saat ingest berjalan, akan terjadi error "AlreadyLocked".
  Solusi: gunakan _qdrant_search() yang selalu buka + tutup client.
"""

import os
import re
import csv
import threading
from typing import Any, Dict, List, Optional, Tuple

from modules.qdrant_client_factory import (
    get_qdrant_client as _factory_get_client,
    COLLECTION_NAME,
)

# ── Constants ──────────────────────────────────────────────────────────────────

DATASET_DIR = os.path.join(
    os.path.dirname(os.path.dirname(__file__)),
    "data",
    "dataset_scincare",
)
PRODUCTS_CSV = os.path.join(DATASET_DIR, "incidecoder_products.csv")

# Minimum cosine similarity to consider an ingredient "semantically similar"
SEMANTIC_THRESHOLD = 0.72

# Maximum similar ingredients to look up per query ingredient
TOP_K_PER_INGREDIENT = 8

# Minimum score fraction (0..1) for a product to be included in results
MIN_PRODUCT_SCORE = 0.10

# ── Ingest lock flag ───────────────────────────────────────────────────────────
# Saat backend melakukan reingest (via /admin/reingest), flag ini True
# sehingga semantic search dilewati (fallback ke string-overlap)

_is_ingesting: bool = False
_ingest_lock = threading.Lock()


def set_ingesting(state: bool) -> None:
    """Dipanggil oleh endpoint /admin/reingest untuk block semantic search."""
    global _is_ingesting
    _is_ingesting = state


# ── In-memory cache ────────────────────────────────────────────────────────────

_products_cache: List[Dict[str, Any]] = []
_products_by_id_cache: Dict[str, Dict[str, Any]] = {}


def _load_products() -> Tuple[List[Dict[str, Any]], Dict[str, Dict[str, Any]]]:
    """Load dan cache incidecoder_products.csv dalam dua bentuk:
    - list  untuk string-overlap fallback
    - dict  keyed by product id untuk semantic lookup
    """
    global _products_cache, _products_by_id_cache
    if _products_cache:
        return _products_cache, _products_by_id_cache

    if not os.path.exists(PRODUCTS_CSV):
        return [], {}

    products_list: List[Dict[str, Any]] = []
    products_by_id: Dict[str, Dict[str, Any]] = {}

    with open(PRODUCTS_CSV, encoding="utf-8-sig", errors="ignore", newline="") as f:
        reader = csv.DictReader(f)
        for row in reader:
            pid = str(row.get("id") or "").strip()
            name = str(row.get("product_name") or "").strip()
            brand = str(row.get("brand") or "").strip()
            if not name:
                continue

            raw = str(row.get("ingredient_raw") or "")
            ings = [
                re.sub(r"\s*\([^)]*\)", "", part).strip().lower()
                for part in raw.split(",")
                if part.strip()
            ]
            ings = [i for i in ings if i]

            entry = {
                "id": pid,
                "name": name,
                "brand": brand,
                "category": str(row.get("category") or "").strip(),
                "url": str(row.get("product_url") or "").strip(),
                "ingredients": ings,
            }
            products_list.append(entry)
            if pid:
                products_by_id[pid] = entry

    _products_cache = [p for p in products_list if p["name"]]
    _products_by_id_cache = products_by_id
    return _products_cache, _products_by_id_cache


# ── String-overlap fallback ────────────────────────────────────────────────────

def _string_overlap_score(
    query_ings: List[str], product_ings: List[str]
) -> Tuple[float, List[str]]:
    """Recall-based score: fraksi query ingredients yang ditemukan di produk."""
    if not query_ings or not product_ings:
        return 0.0, []

    matched: List[str] = []
    for qi in query_ings:
        q = qi.lower().strip()
        if not q:
            continue
        for pi in product_ings:
            if q in pi or pi in q:
                matched.append(qi)
                break

    score = len(matched) / len(query_ings) if query_ings else 0.0
    return round(score, 4), matched[:4]


def get_string_overlap_recommendations(
    ingredient_names: List[str],
    limit: int = 8,
) -> List[Dict[str, Any]]:
    """Classic string-overlap recommendations (legacy strategy)."""
    products, _ = _load_products()
    query_ings = [i.strip().lower() for i in ingredient_names if i.strip()]
    if not query_ings or not products:
        return []

    scored = []
    for product in products:
        score, matched = _string_overlap_score(query_ings, product["ingredients"])
        if score <= 0:
            continue
        scored.append({
            "_score": score,
            "name": product["name"],
            "brand": product["brand"],
            "category_tags": product.get("category", ""),
            "url": product.get("url", ""),
            "similarity_pct": min(round(score * 100), 99),
            "matched_ingredients": matched,
            "match_reason": "Komposisi bahan serupa",
        })

    scored.sort(key=lambda x: x["_score"], reverse=True)
    return [{k: v for k, v in e.items() if k != "_score"} for e in scored[:limit]]


# ── Semantic strategy via Qdrant ───────────────────────────────────────────────

def _get_embedding(text: str) -> Optional[List[float]]:
    """Wrapper around the project's existing embedding utility."""
    try:
        from modules.embedding_utils import get_embedding
        return get_embedding(text)
    except Exception:
        return None


def _qdrant_search(vector: List[float], limit: int, threshold: float) -> List[Any]:
    """
    Buka Qdrant, lakukan search, tutup client segera setelahnya.
    
    Pola buka-pakai-tutup ini penting untuk file-local mode agar tidak
    ada file lock yang tersisa setelah fungsi selesai.
    """
    client = None
    try:
        client = _factory_get_client()
        results = client.search(
            collection_name=COLLECTION_NAME,
            query_vector=vector,
            limit=limit,
            score_threshold=threshold,
        )
        return results
    except Exception:
        return []
    finally:
        # KRITIS: selalu tutup client agar file lock dilepas
        if client is not None:
            try:
                client.close()
            except Exception:
                pass


def get_semantic_recommendations(
    ingredient_names: List[str],
    limit: int = 8,
    semantic_threshold: float = SEMANTIC_THRESHOLD,
) -> List[Dict[str, Any]]:
    """
    Semantic product recommendation via Qdrant similarity search.

    Steps:
    1. Untuk setiap ingredient yang di-scan, embed namanya dan cari di Qdrant
       ingredient paling mirip secara semantik (cosine similarity > threshold).
    2. Kumpulkan related_product_ids dari payload setiap hit.
    3. Score tiap produk berdasarkan berapa banyak query ingredient yang
       punya match semantik di dalam ingredient list produk tersebut.
    4. Enrich dengan metadata produk dan return sorted results.
    """
    # Skip jika sedang proses ingest (hindari lock conflict)
    if _is_ingesting:
        return []

    _, products_by_id = _load_products()
    if not products_by_id:
        return []

    # product_id → {score_sum, hit_count, matched_pairs}
    product_votes: Dict[str, Dict[str, Any]] = {}

    for ing_name in ingredient_names:
        ing_name = ing_name.strip()
        if not ing_name:
            continue

        vector = _get_embedding(ing_name)
        if not vector:
            continue

        # Buka Qdrant, search, tutup — semua dalam satu call
        hits = _qdrant_search(vector, TOP_K_PER_INGREDIENT, semantic_threshold)

        for hit in hits:
            payload = hit.payload or {}
            related_pids = payload.get("related_product_ids") or []
            sim_score = hit.score
            similar_name = payload.get("name", "")
            functions = payload.get("functions", "")

            for pid in related_pids:
                pid = str(pid)
                if pid not in product_votes:
                    product_votes[pid] = {
                        "score_sum": 0.0,
                        "hit_count": 0,
                        "matched_pairs": [],
                    }
                product_votes[pid]["score_sum"] += sim_score
                product_votes[pid]["hit_count"] += 1
                product_votes[pid]["matched_pairs"].append(
                    (ing_name, similar_name, functions, round(sim_score, 3))
                )

    if not product_votes:
        return []

    n_query = len([i for i in ingredient_names if i.strip()])

    results = []
    for pid, data in product_votes.items():
        prod = products_by_id.get(pid)
        if not prod:
            continue

        avg_sim = data["score_sum"] / data["hit_count"] if data["hit_count"] else 0
        coverage = min(data["hit_count"] / n_query, 1.0) if n_query else 0
        final_score = avg_sim * 0.6 + coverage * 0.4

        if final_score < MIN_PRODUCT_SCORE:
            continue

        seen_query_ings = set()
        matched_display = []
        match_functions = set()
        for q_ing, s_ing, funcs, sim in data["matched_pairs"]:
            if q_ing not in seen_query_ings:
                seen_query_ings.add(q_ing)
                label = q_ing if q_ing.lower() == s_ing.lower() else f"{q_ing}≈{s_ing}"
                matched_display.append(label)
            if funcs:
                for f in funcs.split(","):
                    f = f.strip()
                    if f:
                        match_functions.add(f)

        if match_functions:
            reason_funcs = ", ".join(sorted(match_functions)[:3])
            match_reason = f"Fungsi serupa: {reason_funcs}"
        else:
            match_reason = "Komposisi bahan serupa"

        results.append({
            "_score": final_score,
            "name": prod["name"],
            "brand": prod.get("brand", ""),
            "category_tags": prod.get("category", ""),
            "url": prod.get("url", ""),
            "similarity_pct": min(round(final_score * 100), 99),
            "matched_ingredients": matched_display[:4],
            "match_reason": match_reason,
        })

    results.sort(key=lambda x: x["_score"], reverse=True)
    seen_names = set()
    deduped = []
    for r in results:
        key = r["name"].lower().strip()
        if key not in seen_names:
            seen_names.add(key)
            deduped.append({k: v for k, v in r.items() if k != "_score"})

    return deduped[:limit]


# ── Public hybrid API ──────────────────────────────────────────────────────────

def get_recommendations(
    ingredient_names: List[str],
    limit: int = 8,
    mode: str = "auto",
) -> List[Dict[str, Any]]:
    """
    Get product recommendations using the best available strategy.

    mode:
      'semantic'  — Qdrant semantic search only
      'overlap'   — string-overlap only (legacy, fast)
      'auto'      — semantic first, fallback ke overlap jika < 3 hasil
    """
    if mode == "overlap":
        return get_string_overlap_recommendations(ingredient_names, limit)

    if mode == "semantic":
        return get_semantic_recommendations(ingredient_names, limit)

    # auto: prefer semantic, fallback to overlap
    semantic_results = get_semantic_recommendations(ingredient_names, limit)
    if len(semantic_results) >= 3:
        return semantic_results

    # Fallback: merge semantic + overlap
    overlap_results = get_string_overlap_recommendations(ingredient_names, limit)

    seen = {r["name"].lower().strip() for r in semantic_results}
    merged = list(semantic_results)
    for r in overlap_results:
        key = r["name"].lower().strip()
        if key not in seen:
            seen.add(key)
            merged.append(r)
        if len(merged) >= limit:
            break

    return merged[:limit]
