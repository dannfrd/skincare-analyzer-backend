import csv
import difflib
import os
import re
from functools import lru_cache
from typing import Any, Dict, List, Tuple


DEFAULT_DATASET_PATH = os.path.join(
    os.path.dirname(os.path.dirname(__file__)),
    "data",
    "dataset_scincare",
    "ingredientsList.csv",
)


def _normalize_name(value: str) -> str:
    normalized = re.sub(r"[^A-Za-z0-9\s\-\+\./]", " ", value.upper())
    return re.sub(r"\s+", " ", normalized).strip()


def _clip(value: str, max_len: int = 220) -> str:
    compact = re.sub(r"\s+", " ", value or "").strip()
    if len(compact) <= max_len:
        return compact
    return compact[: max_len - 3].rstrip() + "..."


@lru_cache(maxsize=1)
def _load_ingredient_knowledge() -> Dict[str, Dict[str, str]]:
    dataset_path = os.getenv("RAG_INGREDIENT_DATASET", DEFAULT_DATASET_PATH)
    if not os.path.exists(dataset_path):
        return {}

    knowledge: Dict[str, Dict[str, str]] = {}
    with open(dataset_path, "r", encoding="utf-8-sig", errors="ignore", newline="") as csv_file:
        reader = csv.DictReader(csv_file)
        for row in reader:
            name = str(row.get("name") or row.get("Name") or "").strip()
            if not name:
                continue

            key = _normalize_name(name)
            if not key or key in knowledge:
                continue

            knowledge[key] = {
                "name": name.strip(),
                "short_description": str(row.get("short_description") or "").strip(),
                "what_is_it": str(row.get("what_is_it") or "").strip(),
                "what_does_it_do": str(row.get("what_does_it_do") or "").strip(),
                "who_is_it_good_for": str(row.get("who_is_it_good_for") or "").strip(),
                "who_should_avoid": str(row.get("who_should_avoid") or "").strip(),
            }

    return knowledge


def build_rag_context(
    ingredient_tokens: List[str],
    top_k: int | None = None,
) -> Tuple[str, Dict[str, Any]]:
    cleaned_tokens = [token.strip() for token in ingredient_tokens if token and token.strip()]
    if not cleaned_tokens:
        return "", {"enabled": False, "reason": "empty_tokens", "items": []}

    knowledge = _load_ingredient_knowledge()
    if not knowledge:
        return "", {
            "enabled": False,
            "reason": "dataset_unavailable",
            "dataset_path": os.getenv("RAG_INGREDIENT_DATASET", DEFAULT_DATASET_PATH),
            "items": [],
        }

    fuzzy_cutoff = float(os.getenv("RAG_FUZZY_THRESHOLD", "0.84"))
    max_items = top_k or int(os.getenv("RAG_MAX_CONTEXT_ITEMS", "12"))
    known_keys = list(knowledge.keys())

    selected_items: List[Dict[str, str]] = []
    selected_keys = set()

    for token in cleaned_tokens:
        normalized_token = _normalize_name(token)
        if not normalized_token:
            continue

        matched_key = ""
        match_type = ""

        if normalized_token in knowledge:
            matched_key = normalized_token
            match_type = "exact"
        else:
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
        item = dict(knowledge[matched_key])
        item["token"] = token
        item["match_type"] = match_type
        selected_items.append(item)

        if len(selected_items) >= max_items:
            break

    if not selected_items:
        return "", {
            "enabled": True,
            "reason": "no_retrieval_match",
            "dataset_path": os.getenv("RAG_INGREDIENT_DATASET", DEFAULT_DATASET_PATH),
            "items": [],
        }

    lines = ["Dataset context (trusted ingredient evidence):"]
    for index, item in enumerate(selected_items, start=1):
        parts = []
        if item.get("short_description"):
            parts.append(f"ringkas: {_clip(item['short_description'])}")
        if item.get("what_is_it"):
            parts.append(f"definisi: {_clip(item['what_is_it'])}")
        if item.get("what_does_it_do"):
            parts.append(f"fungsi: {_clip(item['what_does_it_do'])}")
        if item.get("who_is_it_good_for"):
            parts.append(f"cocok: {_clip(item['who_is_it_good_for'])}")
        if item.get("who_should_avoid"):
            parts.append(f"hindari: {_clip(item['who_should_avoid'])}")

        context_payload = " | ".join(parts) if parts else "data terbatas"
        lines.append(f"{index}. {item['name']} ({item['match_type']}): {context_payload}")

    return "\n".join(lines), {
        "enabled": True,
        "reason": "ok",
        "dataset_path": os.getenv("RAG_INGREDIENT_DATASET", DEFAULT_DATASET_PATH),
        "items": selected_items,
    }