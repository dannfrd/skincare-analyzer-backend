import csv
import difflib
import os
import re
from functools import lru_cache
from typing import Any, Dict, List, Tuple


# Dataset paths
DATASET_DIR = os.path.join(
    os.path.dirname(os.path.dirname(__file__)),
    "data",
    "dataset_scincare",
)

DATASET_DESCRIPTIONS = os.path.join(DATASET_DIR, "cosmetic_ingredients_train.csv")
DATASET_CATEGORIES = os.path.join(DATASET_DIR, "ingredients_category.csv")
DATASET_BPOM_HARMFUL = os.path.join(
    DATASET_DIR,
    "Database Kosmetik Mengandung Bahan Berbahaya - Direktorat Standardisasi Obat Tradisional, Suplemen Kesehatan dan Kosmetik.csv"
)


def _normalize_name(value: str) -> str:
    """Normalize ingredient name for matching"""
    normalized = re.sub(r"[^A-Za-z0-9\s\-\+\./]", " ", value.upper())
    return re.sub(r"\s+", " ", normalized).strip()


def _clip(value: str, max_len: int = 220) -> str:
    """Clip text to max length"""
    compact = re.sub(r"\s+", " ", value or "").strip()
    if len(compact) <= max_len:
        return compact
    return compact[: max_len - 3].rstrip() + "..."


@lru_cache(maxsize=1)
def _load_descriptions_dataset() -> Dict[str, Dict[str, str]]:
    """Load cosmetic_ingredients_train.csv - Detailed descriptions"""
    dataset_path = os.getenv("RAG_DATASET_DESCRIPTIONS", DATASET_DESCRIPTIONS)
    if not os.path.exists(dataset_path):
        return {}

    knowledge: Dict[str, Dict[str, str]] = {}
    try:
        with open(dataset_path, "r", encoding="utf-8-sig", errors="ignore", newline="") as csv_file:
            reader = csv.DictReader(csv_file)
            for row in reader:
                name = str(row.get("ingredient") or row.get("name") or row.get("Name") or "").strip()
                if not name:
                    continue

                key = _normalize_name(name)
                if not key or key in knowledge:
                    continue

                description = str(row.get("description") or "").strip()
                
                knowledge[key] = {
                    "name": name.strip(),
                    "description": description,
                    "source": "descriptions_dataset"
                }
    except Exception as e:
        print(f"Error loading descriptions dataset: {e}")
    
    return knowledge


@lru_cache(maxsize=1)
def _load_categories_dataset() -> Dict[str, Dict[str, str]]:
    """Load ingredients_category.csv - Functions, warnings, origin"""
    dataset_path = os.getenv("RAG_DATASET_CATEGORIES", DATASET_CATEGORIES)
    if not os.path.exists(dataset_path):
        return {}

    knowledge: Dict[str, Dict[str, str]] = {}
    try:
        with open(dataset_path, "r", encoding="utf-8-sig", errors="ignore", newline="") as csv_file:
            reader = csv.DictReader(csv_file)
            for row in reader:
                name = str(row.get("ingredient_name") or "").strip()
                if not name:
                    continue

                key = _normalize_name(name)
                if not key or key in knowledge:
                    continue

                function1 = str(row.get("function1") or "").strip()
                function2 = str(row.get("function2") or "").strip()
                warning1 = str(row.get("warning1") or "").strip()
                warning2 = str(row.get("warning2") or "").strip()
                origin = str(row.get("ingredient_origin") or "").strip()
                charge = str(row.get("ingredient_charge") or "").strip()

                functions = [f for f in [function1, function2] if f]
                warnings = [w for w in [warning1, warning2] if w]

                knowledge[key] = {
                    "name": name.strip(),
                    "functions": ", ".join(functions) if functions else "",
                    "warnings": ", ".join(warnings) if warnings else "",
                    "origin": origin,
                    "charge": charge,
                    "source": "categories_dataset"
                }
    except Exception as e:
        print(f"Error loading categories dataset: {e}")
    
    return knowledge


@lru_cache(maxsize=1)
def _load_bpom_harmful_dataset() -> Dict[str, Dict[str, str]]:
    """Load BPOM harmful ingredients dataset"""
    dataset_path = os.getenv("RAG_DATASET_BPOM", DATASET_BPOM_HARMFUL)
    if not os.path.exists(dataset_path):
        return {}

    harmful_ingredients: Dict[str, Dict[str, str]] = {}
    try:
        with open(dataset_path, "r", encoding="utf-8-sig", errors="ignore", newline="") as csv_file:
            reader = csv.DictReader(csv_file)
            for row in reader:
                # Extract harmful ingredient from "Kandungan Bahan Berbahaya/Dilarang" column
                harmful_content = str(row.get("Kandungan Bahan Berbahaya/Dilarang") or "").strip()
                if not harmful_content:
                    continue

                # Normalize and store
                key = _normalize_name(harmful_content)
                if not key:
                    continue

                product_name = str(row.get("Nama Produk") or "").strip()
                warning_number = str(row.get("Nomor Surat Public Warning") or "").strip()

                # Store or append to existing
                if key not in harmful_ingredients:
                    harmful_ingredients[key] = {
                        "name": harmful_content,
                        "harmful": True,
                        "bpom_warning": "BPOM: Bahan berbahaya/dilarang",
                        "found_in_products": [product_name] if product_name else [],
                        "warning_number": warning_number,
                        "source": "bpom_harmful_dataset"
                    }
                else:
                    # Append product if not already listed
                    if product_name and product_name not in harmful_ingredients[key]["found_in_products"]:
                        harmful_ingredients[key]["found_in_products"].append(product_name)
    except Exception as e:
        print(f"Error loading BPOM harmful dataset: {e}")
    
    return harmful_ingredients


def _merge_ingredient_data(
    descriptions: Dict[str, Dict[str, str]],
    categories: Dict[str, Dict[str, str]],
    bpom_harmful: Dict[str, Dict[str, str]],
    ingredient_key: str
) -> Dict[str, Any]:
    """Merge data from all 3 datasets for a single ingredient"""
    merged = {
        "name": "",
        "description": "",
        "functions": "",
        "warnings": "",
        "origin": "",
        "charge": "",
        "harmful": False,
        "bpom_warning": "",
        "sources": []
    }

    # Get data from descriptions dataset
    if ingredient_key in descriptions:
        data = descriptions[ingredient_key]
        merged["name"] = data["name"]
        merged["description"] = data["description"]
        merged["sources"].append("descriptions")

    # Get data from categories dataset
    if ingredient_key in categories:
        data = categories[ingredient_key]
        if not merged["name"]:
            merged["name"] = data["name"]
        merged["functions"] = data["functions"]
        merged["warnings"] = data["warnings"]
        merged["origin"] = data["origin"]
        merged["charge"] = data["charge"]
        merged["sources"].append("categories")

    # Get data from BPOM harmful dataset
    if ingredient_key in bpom_harmful:
        data = bpom_harmful[ingredient_key]
        if not merged["name"]:
            merged["name"] = data["name"]
        merged["harmful"] = True
        merged["bpom_warning"] = data["bpom_warning"]
        merged["sources"].append("bpom_harmful")

    return merged


def build_rag_context(
    ingredient_tokens: List[str],
    top_k: int | None = None,
) -> Tuple[str, Dict[str, Any]]:
    """
    Build RAG context from ALL 3 datasets:
    1. cosmetic_ingredients_train.csv - Detailed descriptions
    2. ingredients_category.csv - Functions, warnings, origin
    3. Database BPOM - Harmful ingredients
    """
    cleaned_tokens = [token.strip() for token in ingredient_tokens if token and token.strip()]
    if not cleaned_tokens:
        return "", {"enabled": False, "reason": "empty_tokens", "items": []}

    # Load all 3 datasets
    descriptions = _load_descriptions_dataset()
    categories = _load_categories_dataset()
    bpom_harmful = _load_bpom_harmful_dataset()

    if not descriptions and not categories and not bpom_harmful:
        return "", {
            "enabled": False,
            "reason": "all_datasets_unavailable",
            "items": [],
        }

    fuzzy_cutoff = float(os.getenv("RAG_FUZZY_THRESHOLD", "0.84"))
    max_items = top_k or int(os.getenv("RAG_MAX_CONTEXT_ITEMS", "12"))

    # Combine all keys for fuzzy matching
    all_keys = set()
    all_keys.update(descriptions.keys())
    all_keys.update(categories.keys())
    all_keys.update(bpom_harmful.keys())
    known_keys = list(all_keys)

    selected_items: List[Dict[str, Any]] = []
    selected_keys = set()

    for token in cleaned_tokens:
        normalized_token = _normalize_name(token)
        if not normalized_token:
            continue

        matched_key = ""
        match_type = ""

        # Try exact match first
        if normalized_token in all_keys:
            matched_key = normalized_token
            match_type = "exact"
        else:
            # Try fuzzy match
            close_matches = difflib.get_close_matches(
                normalized_token,
                known_keys,
                n=1,
                cutoff=fuzzy_cutoff,
            )
            if close_matches:
                matched_key = close_matches[0]
                match_type = "fuzzy"

        if not matched_key or matched_key in selected_keys:
            continue

        selected_keys.add(matched_key)
        
        # Merge data from all 3 datasets
        merged_data = _merge_ingredient_data(
            descriptions, categories, bpom_harmful, matched_key
        )
        merged_data["token"] = token
        merged_data["match_type"] = match_type
        
        selected_items.append(merged_data)

        if len(selected_items) >= max_items:
            break

    if not selected_items:
        return "", {
            "enabled": True,
            "reason": "no_retrieval_match",
            "datasets_loaded": {
                "descriptions": len(descriptions),
                "categories": len(categories),
                "bpom_harmful": len(bpom_harmful)
            },
            "items": [],
        }

    # Build context string
    lines = ["Dataset context (3 trusted sources - descriptions, categories, BPOM):"]
    
    for index, item in enumerate(selected_items, start=1):
        parts = []
        
        # Add description if available
        if item.get("description"):
            parts.append(f"deskripsi: {_clip(item['description'], 180)}")
        
        # Add functions if available
        if item.get("functions"):
            parts.append(f"fungsi: {item['functions']}")
        
        # Add warnings if available
        if item.get("warnings"):
            parts.append(f"⚠️ peringatan: {item['warnings']}")
        
        # Add origin and charge if available
        if item.get("origin"):
            parts.append(f"asal: {item['origin']}")
        
        # Add BPOM warning if harmful
        if item.get("harmful"):
            parts.append(f"🚨 BPOM: BAHAN BERBAHAYA/DILARANG")
        
        # Add sources
        sources_str = ", ".join(item.get("sources", []))
        
        context_payload = " | ".join(parts) if parts else "data terbatas"
        lines.append(
            f"{index}. {item['name']} ({item['match_type']}) [{sources_str}]: {context_payload}"
        )

    return "\n".join(lines), {
        "enabled": True,
        "reason": "ok",
        "datasets_loaded": {
            "descriptions": len(descriptions),
            "categories": len(categories),
            "bpom_harmful": len(bpom_harmful)
        },
        "items": selected_items,
    }
