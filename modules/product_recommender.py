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

def classify_category(name: str) -> str:
    n = name.lower()
    if any(w in n for w in ['sunscreen', 'spf', 'uv', 'sun block', 'sun lotion', 'sun protection']):
        return 'sunscreen'
    if any(w in n for w in ['serum', 'essence', 'ampoule', 'booster', 'concentrate', 'treatment']):
        return 'serum'
    if any(w in n for w in ['cleanser', 'wash', 'foam', 'soap', 'cleansing', 'saponins', 'makeup-melting']):
        return 'cleanser'
    if any(w in n for w in ['moisturizer', 'cream', 'lotion', 'balm', 'gel cream', 'night cream', 'day cream', 'hydrate', 'moisturising']):
        return 'moisturizer'
    if any(w in n for w in ['toner', 'mist', 'spray', 'softening lotion']):
        return 'toner'
    if any(w in n for w in ['mask', 'sheet', 'peeling', 'peel', 'exfoliat', 'clay']):
        return 'mask'
    if any(w in n for w in ['oil', 'butter']):
        return 'oil'
    return 'other'


def standardize_category(cat_str: Optional[str]) -> str:
    if not cat_str:
        return ""
    c = cat_str.lower().strip()
    if any(w in c for w in ['sunscreen', 'spf', 'uv', 'sun']):
        return 'sunscreen'
    if any(w in c for w in ['serum', 'essence', 'ampoule', 'booster', 'treatment']):
        return 'serum'
    if any(w in c for w in ['cleanser', 'wash', 'foam', 'soap', 'cleansing', 'facial wash', 'sabun']):
        return 'cleanser'
    if any(w in c for w in ['moisturizer', 'cream', 'lotion', 'balm', 'pelembab', 'moisturising']):
        return 'moisturizer'
    if any(w in c for w in ['toner', 'mist', 'spray', 'penyegar']):
        return 'toner'
    if any(w in c for w in ['mask', 'sheet', 'masker', 'peel', 'exfoliat']):
        return 'mask'
    return c

# ── Constants ──────────────────────────────────────────────────────────────────

DATASET_DIR = os.path.join(
    os.path.dirname(os.path.dirname(__file__)),
    "data",
    "dataset_scincare",
)
PRODUCTS_CSV = os.path.join(DATASET_DIR, "incidecoder_products.csv")
SKINCARISMA_PRODUCTS_CSV = os.path.join(DATASET_DIR, "skincarisma_products.csv")

# Minimum cosine similarity to consider an ingredient "semantically similar"
SEMANTIC_THRESHOLD = 0.68

# Maximum similar ingredients to look up per query ingredient
# Ditingkatkan dari 8 ke 25 karena penambahan 1400+ vektor Skincarisma membuat node produk terdorong ke rank lebih rendah
TOP_K_PER_INGREDIENT = 25

# Minimum score fraction (0..1) for a product to be included in results
MIN_PRODUCT_SCORE = 0.08


# ── Active Ingredients Database ────────────────────────────────────────────────
ACTIVE_INGREDIENTS_MAP = {
    # Brightening / Hyperpigmentation
    "niacinamide": {"concerns": ["dullness", "hyperpigmentation", "acne", "barrier"], "skin_types": ["normal", "dry", "oily", "combination", "sensitive"], "synergies": ["retinol", "hyaluronic acid"]},
    "vitamin c": {"concerns": ["dullness", "hyperpigmentation", "aging"], "skin_types": ["normal", "dry", "oily", "combination"], "conflicts": ["retinol", "salicylic acid", "glycolic acid", "lactic acid"]},
    "ascorbic acid": {"concerns": ["dullness", "hyperpigmentation", "aging"], "skin_types": ["normal", "dry", "oily", "combination"], "conflicts": ["retinol", "salicylic acid", "glycolic acid", "lactic acid"]},
    "arbutin": {"concerns": ["dullness", "hyperpigmentation"], "skin_types": ["normal", "dry", "oily", "combination", "sensitive"]},
    "alpha arbutin": {"concerns": ["dullness", "hyperpigmentation"], "skin_types": ["normal", "dry", "oily", "combination", "sensitive"]},
    "tranexamic acid": {"concerns": ["hyperpigmentation", "barrier"], "skin_types": ["normal", "dry", "oily", "combination", "sensitive"]},
    "kojic acid": {"concerns": ["hyperpigmentation"], "skin_types": ["normal", "dry", "oily", "combination"]},
    "glutathione": {"concerns": ["dullness", "hyperpigmentation"], "skin_types": ["normal", "dry", "oily", "combination"]},

    # Acne / Exfoliation / Oily Skin
    "salicylic acid": {"concerns": ["acne", "oily", "blackheads"], "skin_types": ["oily", "combination"], "conflicts": ["retinol", "vitamin c", "ascorbic acid", "glycolic acid", "lactic acid"]},
    "bha": {"concerns": ["acne", "oily", "blackheads"], "skin_types": ["oily", "combination"], "conflicts": ["retinol", "vitamin c", "ascorbic acid", "glycolic acid", "lactic acid"]},
    "glycolic acid": {"concerns": ["acne", "dullness", "aging"], "skin_types": ["normal", "oily", "combination"], "conflicts": ["retinol", "vitamin c", "ascorbic acid", "salicylic acid", "lactic acid"]},
    "lactic acid": {"concerns": ["acne", "dullness", "dryness"], "skin_types": ["normal", "dry", "combination"], "conflicts": ["retinol", "vitamin c", "ascorbic acid", "salicylic acid", "glycolic acid"]},
    "aha": {"concerns": ["acne", "dullness", "aging", "dryness"], "skin_types": ["normal", "dry", "oily", "combination"], "conflicts": ["retinol", "vitamin c", "ascorbic acid", "salicylic acid", "glycolic acid", "lactic acid"]},
    "tea tree": {"concerns": ["acne", "oily"], "skin_types": ["oily", "combination", "sensitive"]},
    "azelaic acid": {"concerns": ["acne", "hyperpigmentation", "redness"], "skin_types": ["normal", "dry", "oily", "combination", "sensitive"]},

    # Anti-Aging
    "retinol": {"concerns": ["aging", "wrinkles", "acne"], "skin_types": ["normal", "dry", "oily", "combination"], "conflicts": ["salicylic acid", "glycolic acid", "lactic acid", "vitamin c", "ascorbic acid"], "synergies": ["niacinamide", "ceramide", "hyaluronic acid"]},
    "retinal": {"concerns": ["aging", "wrinkles", "acne"], "skin_types": ["normal", "dry", "oily", "combination"], "conflicts": ["salicylic acid", "glycolic acid", "lactic acid", "vitamin c", "ascorbic acid"]},
    "bakuchiol": {"concerns": ["aging", "wrinkles", "acne"], "skin_types": ["normal", "dry", "oily", "combination", "sensitive"], "synergies": ["retinol"]},
    "peptide": {"concerns": ["aging", "wrinkles", "barrier"], "skin_types": ["normal", "dry", "oily", "combination", "sensitive"]},
    "collagen": {"concerns": ["aging", "dryness"], "skin_types": ["normal", "dry", "oily", "combination", "sensitive"]},

    # Hydration / Barrier Repair / Soothing
    "ceramide": {"concerns": ["barrier", "dryness", "sensitive", "redness"], "skin_types": ["normal", "dry", "oily", "combination", "sensitive"], "synergies": ["hyaluronic acid", "retinol"]},
    "hyaluronic acid": {"concerns": ["dryness", "barrier"], "skin_types": ["normal", "dry", "oily", "combination", "sensitive"], "synergies": ["panthenol", "ceramide", "niacinamide"]},
    "sodium hyaluronate": {"concerns": ["dryness", "barrier"], "skin_types": ["normal", "dry", "oily", "combination", "sensitive"]},
    "panthenol": {"concerns": ["barrier", "redness", "sensitive", "dryness"], "skin_types": ["normal", "dry", "oily", "combination", "sensitive"], "synergies": ["hyaluronic acid"]},
    "centella asiatica": {"concerns": ["barrier", "redness", "sensitive", "acne"], "skin_types": ["normal", "dry", "oily", "combination", "sensitive"]},
    "madecassoside": {"concerns": ["barrier", "redness", "sensitive", "acne"], "skin_types": ["normal", "dry", "oily", "combination", "sensitive"]},
    "allantoin": {"concerns": ["redness", "sensitive"], "skin_types": ["normal", "dry", "oily", "combination", "sensitive"]},
    "bisabolol": {"concerns": ["redness", "sensitive"], "skin_types": ["normal", "dry", "oily", "combination", "sensitive"]},
    "aloe vera": {"concerns": ["dryness", "redness", "sensitive"], "skin_types": ["normal", "dry", "oily", "combination", "sensitive"]},
    "calendula": {"concerns": ["redness", "sensitive"], "skin_types": ["normal", "dry", "oily", "combination", "sensitive"]},
    "licorice": {"concerns": ["redness", "hyperpigmentation", "sensitive"], "skin_types": ["normal", "dry", "oily", "combination", "sensitive"]},
    "squalane": {"concerns": ["dryness", "barrier"], "skin_types": ["normal", "dry", "oily", "combination", "sensitive"]},
    "green tea": {"concerns": ["redness", "oily", "acne"], "skin_types": ["normal", "dry", "oily", "combination", "sensitive"]},
    "mugwort": {"concerns": ["barrier", "redness", "sensitive", "acne"], "skin_types": ["normal", "dry", "oily", "combination", "sensitive"]},
}


def _get_active_ingredient_properties(ing_name: str) -> Optional[Dict[str, Any]]:
    """Mendapatkan metadata kecocokan kulit & efek dari nama bahan aktif."""
    name_lower = ing_name.strip().lower()
    for key, props in ACTIVE_INGREDIENTS_MAP.items():
        if key in name_lower or name_lower in key:
            return props
    return None


def check_compatibility(active_ings: List[str]) -> Dict[str, List[Dict[str, Any]]]:
    """Mengecek apakah di antara bahan aktif yang di-scan terdapat sinergi atau konflik kompatibilitas."""
    conflicts = []
    synergies = []
    
    active_props = {}
    for ing in active_ings:
        props = _get_active_ingredient_properties(ing)
        if props:
            active_props[ing.lower().strip()] = props
            
    present_actives = list(active_props.keys())
    
    for i in range(len(present_actives)):
        for j in range(i + 1, len(present_actives)):
            act1 = present_actives[i]
            act2 = present_actives[j]
            
            props1 = active_props[act1]
            props2 = active_props[act2]
            
            if act2 in props1.get("conflicts", []) or act1 in props2.get("conflicts", []):
                name1 = next(ing for ing in active_ings if ing.lower().strip() == act1)
                name2 = next(ing for ing in active_ings if ing.lower().strip() == act2)
                
                msg = f"Kombinasi {name1} + {name2} dapat memicu iritasi kulit (terutama untuk kulit sensitif). Gunakan di waktu yang berbeda (pagi/malam) atau secara bergantian."
                conflicts.append({
                    "ingredients": [name1, name2],
                    "message": msg
                })
                
            if act2 in props1.get("synergies", []) or act1 in props2.get("synergies", []):
                name1 = next(ing for ing in active_ings if ing.lower().strip() == act1)
                name2 = next(ing for ing in active_ings if ing.lower().strip() == act2)
                
                msg = f"Kombinasi {name1} + {name2} bekerja secara sinergis meningkatkan hasil perawatan."
                synergies.append({
                    "ingredients": [name1, name2],
                    "message": msg
                })
                
    return {
        "conflicts": conflicts,
        "synergies": synergies
    }


def get_routine_recommendation_tip(category: Optional[str]) -> str:
    """Memberikan saran langkah perawatan kulit berikutnya berdasarkan kategori yang di-scan."""
    if not category:
        return "Gunakan produk hidrasi dan tabir surya setelah perawatan aktif."
        
    cat = category.lower().strip()
    if cat == "cleanser":
        return "Setelah membersihkan wajah, gunakan Toner hidrasi dan Moisturizer untuk menjaga kelembapan kulit."
    elif cat == "toner":
        return "Lanjutkan dengan Serum bahan aktif (jika ada) dan Moisturizer untuk mengunci kelembapan."
    elif cat == "serum":
        return "Kunci bahan aktif serum Anda dengan Moisturizer. Jangan lupa Sunscreen jika digunakan di pagi hari."
    elif cat == "moisturizer":
        return "Gunakan Sunscreen (pagi) sebagai langkah penutup rutinitas perawatan kulit Anda."
    elif cat == "sunscreen":
        return "Gunakan Pembersih wajah (Cleanser/Double Cleanser) di malam hari untuk membersihkan residu sunscreen secara menyeluruh."
    elif cat == "exfoliator":
        return "Setelah eksfoliasi, hindari bahan aktif iritatif (seperti Retinol/Vit C) dan gunakan Ceramide atau Centella untuk meredakan kulit."
    return "Lanjutkan rutinitas perawatan kulit dasar Anda dengan pembersih, pelembap, dan tabir surya."

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


def _clean_ing(part: str) -> str:
    part = re.sub(r'[\u200b\u200c\u200d\ufeff\xa0]', ' ', part)
    part = re.sub(r"\s*\([^)]*\)", "", part)
    return re.sub(r'\s+', ' ', part).strip().lower()


def _load_products() -> Tuple[List[Dict[str, Any]], Dict[str, Dict[str, Any]]]:
    """Load dan cache incidecoder_products.csv dan skincarisma_products.csv."""
    global _products_cache, _products_by_id_cache
    if _products_cache:
        return _products_cache, _products_by_id_cache

    products_list: List[Dict[str, Any]] = []
    products_by_id: Dict[str, Dict[str, Any]] = {}

    # 1. Load INCIDecoder products
    if os.path.exists(PRODUCTS_CSV):
        with open(PRODUCTS_CSV, encoding="utf-8-sig", errors="ignore", newline="") as f:
            reader = csv.DictReader(f)
            for row in reader:
                pid = str(row.get("id") or "").strip()
                name = str(row.get("product_name") or "").strip()
                brand = str(row.get("brand") or "").strip()
                if not name:
                    continue

                raw = str(row.get("ingredient_raw") or "")
                ings = [_clean_ing(part) for part in raw.split(",") if part.strip()]
                ings = [i for i in ings if i]

                entry = {
                    "id": pid,
                    "name": name,
                    "brand": brand,
                    "category": str(row.get("category") or "").strip(),
                    "url": str(row.get("product_url") or "").strip(),
                    "ingredients": ings,
                    "price": str(row.get("price") or "").strip(),
                }
                products_list.append(entry)
                if pid:
                    products_by_id[pid] = entry

    # 2. Load Skincarisma products (prefixing IDs with sc_)
    if os.path.exists(SKINCARISMA_PRODUCTS_CSV):
        with open(SKINCARISMA_PRODUCTS_CSV, encoding="utf-8-sig", errors="ignore", newline="") as f:
            reader = csv.DictReader(f)
            for row in reader:
                pid = str(row.get("id") or "").strip()
                name = str(row.get("product_name") or "").strip()
                brand = str(row.get("brand") or "").strip()
                if not name:
                    continue

                namespaced_pid = f"sc_{pid}"
                raw = str(row.get("ingredient_raw") or "")
                ings = [_clean_ing(part) for part in raw.split(",") if part.strip()]
                ings = [i for i in ings if i]

                entry = {
                    "id": namespaced_pid,
                    "name": name,
                    "brand": brand,
                    "category": str(row.get("category") or "").strip(),
                    "url": str(row.get("product_url") or "").strip(),
                    "ingredients": ings,
                    "price": str(row.get("price") or "").strip(),
                }
                products_list.append(entry)
                products_by_id[namespaced_pid] = entry

    _products_cache = [p for p in products_list if p["name"]]
    _products_by_id_cache = products_by_id
    return _products_cache, _products_by_id_cache


def clear_recommender_cache() -> None:
    """Clear cached products and force reload from CSV on next request."""
    global _products_cache, _products_by_id_cache
    _products_cache = []
    _products_by_id_cache = {}
    print("[recommender] In-memory products cache cleared.")


# ── Active Ingredients Filtering ───────────────────────────────────────────────

def filter_active_ingredients(ingredient_names: List[str]) -> List[str]:
    """
    Memfilter daftar bahan agar rekomendasi produk hanya mengambil bahan aktif 
    (key ingredients / beneficial actives) seperti Niacinamide, Retinol, Salicylic Acid, 
    Centella, Ceramide, Ekstrak Alami, Vitamin, dll.
    Mengabaikan bahan dasar umum (air, pelarut, pengawet, pengemulsi, pewangi, pengental).
    """
    if not ingredient_names:
        return []
        
    inactive_blacklist = {
        'AQUA', 'WATER', 'GLYCERIN', 'BUTYLENE GLYCOL', 'PROPYLENE GLYCOL', 'DIPROPYLENE GLYCOL',
        'PROPANEDIOL', 'ALCOHOL', 'ALCOHOL DENAT', 'PHENOXYETHANOL', 'CHLORPHENESIN', 'PARABEN',
        'METHYLPARABEN', 'PROPYLPARABEN', 'ETHYLPARABEN', 'BUTYLPARABEN', 'EDTA', 'DISODIUM EDTA',
        'TETRASODIUM EDTA', 'FRAGRANCE', 'PARFUM', 'AROMA', 'LINALOOL', 'LIMONENE', 'GERANIOL',
        'CITRONELLOL', 'CITRAL', 'CARBOMER', 'XANTHAN GUM', 'PVP', 'DIMETHICONE', 'CYCLOPENTASILOXANE',
        'CYCLOHEXASILOXANE', 'MINERAL OIL', 'PARAFFIN', 'PETROLATUM', 'STEARIC ACID', 'CETEARYL ALCOHOL',
        'CETYL ALCOHOL', 'GLYCERYL STEARATE', 'COCAMIDOPROPYL BETAINE', 'SODIUM LAURYL SULFATE',
        'SODIUM LAURETH SULFATE', 'SODIUM BENZOATE', 'POTASSIUM SORBATE', 'CITRIC ACID', 'SODIUM HYDROXIDE',
        'TRIETHANOLAMINE', 'AMINOMETHYL PROPANOL', 'MICA', 'SILICA', 'BHT', 'DISODIUM PHOSPHATE',
        'SODIUM PHOSPHATE', 'HYDROXYETHYLCELLULOSE', 'POLYSORBATE 20', 'POLYSORBATE 60', 'POLYSORBATE 80',
        'POLYSORBATE', 'TRIDECETH-9', 'PEG-HYDROGENATED CASTOR OIL', '1,2-HEXANEDIOL', 'CAPRYLYL GLYCOL'
    }
    
    active_keywords = (
        'NIACINAMIDE', 'RETINOL', 'RETINAL', 'BAKUCHIOL', 'ARBUTIN', 'TRANEXAMIC', 'ASCORBIC', 'VITAMIN C',
        'VITAMIN E', 'TOCOPHEROL', 'SALICYLIC', 'GLYCOLIC', 'LACTIC', 'MANDELIC', 'AZELAIC', 'GLUCONOLACTONE',
        'CENTELLA', 'MADECASSOSIDE', 'ASIATICOSIDE', 'CERAMIDE', 'HYALURONIC', 'HYALURONATE', 'PANTHENOL',
        'ALLANTOIN', 'BISABOLOL', 'ALOE', 'CALENDULA', 'LICORICE', 'GLYCYRRHIZA', 'TEA TREE', 'MELALEUCA',
        'CAMELLIA', 'GREEN TEA', 'MUGWORT', 'ARTEMISIA', 'SNAIL', 'GLUCAN', 'PROPOLIS', 'BIFIDA', 'FERMENT',
        'PEPTIDE', 'COLLAGEN', 'ZINC', 'CAFFEINE', 'SQUALANE', 'ROSEHIP', 'GINSENG', 'EXTRACT', 'FILTRATE',
        'OIL', 'BUTTER', 'ACID', 'RESVERATROL', 'GLUTATHIONE', 'UVINUL', 'TINOSORB', 'AVOBENZONE', 'OCTINOXATE',
        'EXFOLIAT', 'BRIGHTEN', 'SOOTH'
    )
    
    filtered = []
    for ing in ingredient_names:
        ing_upper = ing.strip().upper()
        if not ing_upper:
            continue
            
        # Check blacklist and common prefix patterns
        if ing_upper in inactive_blacklist:
            continue
        if any(ing_upper.startswith(prefix) for prefix in ('PEG-', 'PPG-', 'POLYSORBATE', 'CI ', 'POLYACRYLATE', 'TRIDECETH', 'CETEARETH', 'LAURETH', 'ISOPARAFFIN', 'ISOPROPYL')):
            continue
            
        # Check if it matches active keyword or is not a basic chemical
        if any(kw in ing_upper for kw in active_keywords):
            filtered.append(ing)
            
    # Fallback: jika setelah difilter ternyata kosong (misal produk sangat sederhana),
    # kembalikan bahan yang tidak termasuk blacklist
    if not filtered:
        for ing in ingredient_names:
            ing_upper = ing.strip().upper()
            if ing_upper and ing_upper not in inactive_blacklist and not any(ing_upper.startswith(p) for p in ('PEG-', 'PPG-', 'POLYSORBATE', 'CI ')):
                filtered.append(ing)
                
    active_result = filtered if filtered else ingredient_names
    print(f"[RECOMMENDER] Filtered {len(ingredient_names)} total ingredients -> {len(active_result)} active ingredients: {active_result[:8]}")
    return active_result


# ── String-overlap fallback ────────────────────────────────────────────────────

def _string_overlap_score(
    query_ings: List[str], product_ings: List[str]
) -> Tuple[float, List[str]]:
    """Recall-based score: fraksi query ingredients yang ditemukan di produk."""
    if not query_ings or not product_ings:
        return 0.0, []

    matched: List[str] = []
    valid_queries = [qi for qi in query_ings if len(qi.strip()) >= 3]
    if not valid_queries:
        return 0.0, []

    for qi in valid_queries:
        q = _clean_ing(qi)
        for pi in product_ings:
            # Cegah false positive pada kata terlalu pendek atau umum (min 4 karakter agar zinc, urea, mica masuk)
            if q == pi or (len(q) >= 4 and (q in pi or pi in q)):
                matched.append(qi)
                break

    score = len(matched) / len(valid_queries)
    return round(score, 4), matched[:4]


def get_string_overlap_recommendations(
    ingredient_names: List[str],
    limit: int = 8,
    category: Optional[str] = None,
    skin_type: Optional[str] = None,
    skin_concern: Optional[str] = None,
) -> List[Dict[str, Any]]:
    """Classic string-overlap recommendations with position weighting and skin type/concern boosts."""
    products, _ = _load_products()
    active_ings = filter_active_ingredients(ingredient_names)
    query_ings = [i.strip().lower() for i in active_ings if i.strip()]
    if not query_ings or not products:
        return []

    target_cat = standardize_category(category)

    # Menghitung bobot posisi bahan aktif scan
    total_weight = 0.0
    ing_weights = {}
    for idx, q in enumerate(query_ings):
        weight = max(0.3, 1.0 - (idx * 0.05))
        ing_weights[q] = weight
        total_weight += weight

    scored = []
    for product in products:
        if target_cat:
            prod_cat = classify_category(product["name"] + " " + product.get("category", ""))
            if prod_cat != target_cat:
                continue

        matched = []
        matched_weight_sum = 0.0
        product_ings = product["ingredients"]
        for q in query_ings:
            weight = ing_weights.get(q, 1.0)
            for pi in product_ings:
                if q == pi or (len(q) >= 4 and (q in pi or pi in q)):
                    orig_name = next((ing for ing in active_ings if ing.lower().strip() == q), q)
                    matched.append(orig_name)
                    matched_weight_sum += weight
                    break

        score = matched_weight_sum / total_weight if total_weight else 0.0
        if score <= 0:
            continue

        # Skin profile boost
        boost = 0.0
        concern_match_count = 0
        type_match_count = 0
        matched_concern_ingredients = []

        for ing in product["ingredients"]:
            props = _get_active_ingredient_properties(ing)
            if props:
                if skin_concern and skin_concern.lower() in props.get("concerns", []):
                    concern_match_count += 1
                    matched_concern_ingredients.append(ing)
                if skin_type and skin_type.lower() in props.get("skin_types", []):
                    type_match_count += 1

        if skin_concern and concern_match_count > 0:
            boost += min(0.15, 0.08 + (concern_match_count * 0.02))
        if skin_type and type_match_count > 0:
            boost += min(0.05, 0.02 + (type_match_count * 0.01))

        final_score = score + boost

        suitability_reasons = []
        if skin_type and type_match_count > 0:
            suitability_reasons.append(f"Cocok untuk kulit {skin_type.title()}")
        if skin_concern and concern_match_count > 0:
            suitability_reasons.append(f"Membantu mengatasi {skin_concern.title()}")
            
        suitability_text = " | ".join(suitability_reasons) if suitability_reasons else ""

        scored.append({
            "_score": final_score,
            "name": product["name"],
            "brand": product["brand"],
            "category_tags": product.get("category", ""),
            "url": product.get("url", ""),
            "price": product.get("price", ""),
            "similarity_pct": min(round(final_score * 100), 99),
            "matched_ingredients": matched[:4],
            "match_reason": "Komposisi bahan serupa",
            "skin_suitability": suitability_text,
            "matched_concern_actives": list(set(matched_concern_ingredients))[:3]
        })

    # Fallback jika pencarian terlalu ketat dan mengembalikan 0 hasil
    if target_cat and not scored:
        return get_string_overlap_recommendations(ingredient_names, limit, category=None, skin_type=skin_type, skin_concern=skin_concern)

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
    category: Optional[str] = None,
    skin_type: Optional[str] = None,
    skin_concern: Optional[str] = None,
) -> List[Dict[str, Any]]:
    """
    Semantic product recommendation via Qdrant similarity search with position weighting and skin type/concern boosts.
    """
    # Skip jika sedang proses ingest (hindari lock conflict)
    if _is_ingesting:
        return []

    _, products_by_id = _load_products()
    if not products_by_id:
        return []

    target_cat = standardize_category(category)
    active_ings = filter_active_ingredients(ingredient_names)

    # Menghitung bobot posisi bahan aktif scan
    total_weight = 0.0
    ing_weights = {}
    for idx, ing_name in enumerate(active_ings):
        weight = max(0.3, 1.0 - (idx * 0.05))
        ing_weights[ing_name.lower().strip()] = weight
        total_weight += weight

    # product_id → {score_sum, weight_sum, matched_query_weights, matched_pairs}
    product_votes: Dict[str, Dict[str, Any]] = {}

    for ing_name in active_ings:
        ing_name = ing_name.strip()
        if not ing_name:
            continue

        vector = _get_embedding(ing_name)
        if not vector:
            continue

        # Buka Qdrant, search, tutup — semua dalam satu call
        hits = _qdrant_search(vector, TOP_K_PER_INGREDIENT, semantic_threshold)
        weight = ing_weights.get(ing_name.lower().strip(), 1.0)

        for hit in hits:
            payload = hit.payload or {}
            related_pids = payload.get("related_product_ids") or []
            sim_score = hit.score
            similar_name = payload.get("name", "")
            functions = payload.get("functions", "")

            weighted_score = sim_score * weight

            for pid in related_pids:
                pid = str(pid)
                if pid not in product_votes:
                    product_votes[pid] = {
                        "score_sum": 0.0,
                        "weight_sum": 0.0,
                        "matched_query_weights": {},
                        "matched_pairs": [],
                    }
                product_votes[pid]["score_sum"] += weighted_score
                product_votes[pid]["weight_sum"] += weight
                product_votes[pid]["matched_query_weights"][ing_name.lower().strip()] = weight
                product_votes[pid]["matched_pairs"].append(
                    (ing_name, similar_name, functions, round(sim_score, 3))
                )

    if not product_votes:
        return []

    results = []
    for pid, data in product_votes.items():
        prod = products_by_id.get(pid)
        if not prod:
            continue

        if target_cat:
            prod_cat = classify_category(prod["name"] + " " + prod.get("category", ""))
            if prod_cat != target_cat:
                continue

        weighted_avg_sim = data["score_sum"] / data["weight_sum"] if data["weight_sum"] else 0
        product_matched_weight = sum(data["matched_query_weights"].values())
        weighted_coverage = product_matched_weight / total_weight if total_weight else 0
        
        final_score = weighted_avg_sim * 0.6 + weighted_coverage * 0.4

        # Skin profile boost
        boost = 0.0
        concern_match_count = 0
        type_match_count = 0
        matched_concern_ingredients = []

        for ing in prod["ingredients"]:
            props = _get_active_ingredient_properties(ing)
            if props:
                if skin_concern and skin_concern.lower() in props.get("concerns", []):
                    concern_match_count += 1
                    matched_concern_ingredients.append(ing)
                if skin_type and skin_type.lower() in props.get("skin_types", []):
                    type_match_count += 1

        if skin_concern and concern_match_count > 0:
            boost += min(0.15, 0.08 + (concern_match_count * 0.02))
        if skin_type and type_match_count > 0:
            boost += min(0.05, 0.02 + (type_match_count * 0.01))

        final_score += boost

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

        suitability_reasons = []
        if skin_type and type_match_count > 0:
            suitability_reasons.append(f"Cocok untuk kulit {skin_type.title()}")
        if skin_concern and concern_match_count > 0:
            suitability_reasons.append(f"Membantu mengatasi {skin_concern.title()}")
            
        suitability_text = " | ".join(suitability_reasons) if suitability_reasons else ""

        results.append({
            "_score": final_score,
            "name": prod["name"],
            "brand": prod.get("brand", ""),
            "category_tags": prod.get("category", ""),
            "url": prod.get("url", ""),
            "price": prod.get("price", ""),
            "similarity_pct": min(round(final_score * 100), 99),
            "matched_ingredients": matched_display[:4],
            "match_reason": match_reason,
            "skin_suitability": suitability_text,
            "matched_concern_actives": list(set(matched_concern_ingredients))[:3]
        })

    # Fallback jika pencarian terlalu ketat dan mengembalikan 0 hasil
    if target_cat and not results:
        return get_semantic_recommendations(ingredient_names, limit, semantic_threshold, category=None, skin_type=skin_type, skin_concern=skin_concern)

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
    category: Optional[str] = None,
    skin_type: Optional[str] = None,
    skin_concern: Optional[str] = None,
) -> Dict[str, Any]:
    """
    Get product recommendations using the best available strategy with skin type/concern boosts and compatibility check metadata.
    """
    active_ings = filter_active_ingredients(ingredient_names)
    compatibility_tips = check_compatibility(active_ings)
    routine_tip = get_routine_recommendation_tip(category)

    if mode == "overlap":
        recs = get_string_overlap_recommendations(
            ingredient_names, limit, category=category, skin_type=skin_type, skin_concern=skin_concern
        )
    elif mode == "semantic":
        recs = get_semantic_recommendations(
            ingredient_names, limit, category=category, skin_type=skin_type, skin_concern=skin_concern
        )
    else:
        # auto: prefer semantic, fallback to overlap
        recs = get_semantic_recommendations(
            ingredient_names, limit, category=category, skin_type=skin_type, skin_concern=skin_concern
        )
        if len(recs) < 3:
            overlap_results = get_string_overlap_recommendations(
                ingredient_names, limit, category=category, skin_type=skin_type, skin_concern=skin_concern
            )
            seen = {r["name"].lower().strip() for r in recs}
            for r in overlap_results:
                key = r["name"].lower().strip()
                if key not in seen:
                    seen.add(key)
                    recs.append(r)
                if len(recs) >= limit:
                    break

    return {
        "recommendations": recs[:limit],
        "compatibility_tips": compatibility_tips,
        "routine_tip": routine_tip
    }
