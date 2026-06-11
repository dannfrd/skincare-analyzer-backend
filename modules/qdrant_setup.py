import csv
import os
import re
from typing import Any, Dict, List
from qdrant_client import QdrantClient
from qdrant_client.models import Distance, VectorParams, PointStruct
from modules.embedding_utils import get_embedding

# Dataset paths
DATASET_DIR = os.path.join(
    os.path.dirname(os.path.dirname(__file__)),
    "data",
    "dataset_scincare",
)

DATASET_DESCRIPTIONS = os.path.join(DATASET_DIR, "cosmetic_ingredients.csv")
DATASET_CATEGORIES = os.path.join(DATASET_DIR, "ingredients_category.csv")
DATASET_BPOM_HARMFUL = os.path.join(
    DATASET_DIR,
    "Database Kosmetik Mengandung Bahan Berbahaya - Direktorat Standardisasi Obat Tradisional, Suplemen Kesehatan dan Kosmetik.csv"
)
DATASET_INCIDECODER_INGREDIENTS = os.path.join(DATASET_DIR, "incidecoder_ingredients.csv")
DATASET_INCIDECODER_PRODUCTS = os.path.join(DATASET_DIR, "incidecoder_products.csv")

QDRANT_DATA_DIR = os.path.join(
    os.path.dirname(os.path.dirname(__file__)),
    "qdrant_data"
)

COLLECTION_NAME = "skincare_ingredients"
VECTOR_SIZE = 384  # sentence-transformers all-MiniLM-L6-v2 vector size


def _normalize_name(value: str) -> str:
    """Normalize ingredient name for matching"""
    normalized = re.sub(r"[^A-Za-z0-9\s\-\+\./]", " ", value.upper())
    return re.sub(r"\s+", " ", normalized).strip()


def _clip(value: str, max_len: int = 500) -> str:
    """Clip text to max length"""
    compact = re.sub(r"\s+", " ", value or "").strip()
    if len(compact) <= max_len:
        return compact
    return compact[: max_len - 3].rstrip() + "..."


def _load_descriptions_dataset() -> Dict[str, Dict[str, str]]:
    if not os.path.exists(DATASET_DESCRIPTIONS):
        print(f"Warning: {DATASET_DESCRIPTIONS} not found.")
        return {}

    knowledge: Dict[str, Dict[str, str]] = {}
    try:
        with open(DATASET_DESCRIPTIONS, "r", encoding="utf-8-sig", errors="ignore", newline="") as csv_file:
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


def _load_categories_dataset() -> Dict[str, Dict[str, str]]:
    if not os.path.exists(DATASET_CATEGORIES):
        print(f"Warning: {DATASET_CATEGORIES} not found.")
        return {}

    knowledge: Dict[str, Dict[str, str]] = {}
    try:
        with open(DATASET_CATEGORIES, "r", encoding="utf-8-sig", errors="ignore", newline="") as csv_file:
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


def _load_bpom_harmful_dataset() -> Dict[str, Dict[str, str]]:
    if not os.path.exists(DATASET_BPOM_HARMFUL):
        print(f"Warning: {DATASET_BPOM_HARMFUL} not found.")
        return {}

    harmful_ingredients: Dict[str, Dict[str, str]] = {}
    try:
        with open(DATASET_BPOM_HARMFUL, "r", encoding="utf-8-sig", errors="ignore", newline="") as csv_file:
            reader = csv.DictReader(csv_file)
            for row in reader:
                harmful_content = str(row.get("Kandungan Bahan Berbahaya/Dilarang") or "").strip()
                if not harmful_content:
                    continue

                key = _normalize_name(harmful_content)
                if not key:
                    continue

                product_name = str(row.get("Nama Produk") or "").strip()
                warning_number = str(row.get("Nomor Surat Public Warning") or "").strip()

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
                    if product_name and product_name not in harmful_ingredients[key]["found_in_products"]:
                        harmful_ingredients[key]["found_in_products"].append(product_name)
    except Exception as e:
        print(f"Error loading BPOM harmful dataset: {e}")
    
    return harmful_ingredients


def _load_incidecoder_ingredients_dataset() -> Dict[str, Dict[str, str]]:
    if not os.path.exists(DATASET_INCIDECODER_INGREDIENTS):
        print(f"Warning: {DATASET_INCIDECODER_INGREDIENTS} not found.")
        return {}

    knowledge: Dict[str, Dict[str, str]] = {}
    try:
        with open(
            DATASET_INCIDECODER_INGREDIENTS,
            "r",
            encoding="utf-8-sig",
            errors="ignore",
        ) as csv_file:
            lines = csv_file.read().splitlines()

        for raw_line in lines[1:]:
            line = raw_line.strip()
            if not line:
                continue

            # This export wraps each complete CSV record in an extra quote and
            # appends ";;", so a normal DictReader sees the row as one field.
            if line.startswith('"') and line.endswith('";;'):
                line = line[1:-3]
            elif line.endswith(";;"):
                line = line[:-2]

            line = line.replace('""', '"')
            values = next(csv.reader([line]), [])
            if len(values) < 5:
                continue

            _, name, rating, functions, description = values[:5]
            name = str(name or "").strip()
            if not name:
                continue

            key = _normalize_name(name)
            if not key:
                continue

            description = str(description or "").strip()
            functions = str(functions or "").strip()
            rating = str(rating or "").strip()

            knowledge[key] = {
                "name": name,
                "rating": rating,
                "functions": functions,
                "description": description,
                "source": "incidecoder"
            }
    except Exception as e:
        print(f"Error loading INCIDecoder ingredients: {e}")
    return knowledge


def _load_incidecoder_products_dataset() -> Dict[str, List[str]]:
    if not os.path.exists(DATASET_INCIDECODER_PRODUCTS):
        print(f"Warning: {DATASET_INCIDECODER_PRODUCTS} not found.")
        return {}

    product_mapping: Dict[str, List[str]] = {}
    try:
        with open(DATASET_INCIDECODER_PRODUCTS, "r", encoding="utf-8-sig", errors="ignore", newline="") as csv_file:
            reader = csv.DictReader(csv_file)
            for row in reader:
                product_name = str(row.get("product_name") or "").strip()
                brand = str(row.get("brand") or "").strip()
                ingredients_raw = str(row.get("ingredient_raw") or "").strip()
                
                if not product_name or not ingredients_raw:
                    continue
                
                full_product_name = f"{brand} - {product_name}" if brand else product_name
                ingredient_list = [i.strip() for i in ingredients_raw.split(",")]
                
                for ingredient in ingredient_list:
                    key = _normalize_name(ingredient)
                    if not key:
                        continue
                    
                    if key not in product_mapping:
                        product_mapping[key] = []
                    
                    if full_product_name not in product_mapping[key]:
                        # Limit to 5 products per ingredient
                        if len(product_mapping[key]) < 5:
                            product_mapping[key].append(full_product_name)
    except Exception as e:
        print(f"Error loading INCIDecoder products: {e}")
    
    return product_mapping


def setup_qdrant():
    print("Initializing Qdrant Setup...")
    
    # Initialize datasets
    print("Loading datasets...")
    descriptions = _load_descriptions_dataset()
    categories = _load_categories_dataset()
    bpom_harmful = _load_bpom_harmful_dataset()
    inci_ingredients = _load_incidecoder_ingredients_dataset()
    inci_products = _load_incidecoder_products_dataset()

    # Merge ingredients
    print("Merging dataset entries...")
    all_keys = set()
    all_keys.update(descriptions.keys())
    all_keys.update(categories.keys())
    all_keys.update(bpom_harmful.keys())
    all_keys.update(inci_ingredients.keys())

    merged_data_list = []
    
    for key in all_keys:
        merged = {
            "name": "",
            "normalized_name": key,
            "description": "",
            "functions": "",
            "warnings": "",
            "origin": "",
            "charge": "",
            "harmful": False,
            "bpom_warning": "",
            "rating": "",
            "found_in_products": [],
            "sources": []
        }

        if key in inci_ingredients:
            data = inci_ingredients[key]
            merged["name"] = data["name"]
            merged["description"] = data["description"]
            merged["functions"] = data["functions"]
            merged["rating"] = data["rating"]
            merged["sources"].append("incidecoder")

        if key in descriptions:
            data = descriptions[key]
            if not merged["name"]:
                merged["name"] = data["name"]
            
            if not merged["description"]:
                merged["description"] = data["description"]
            elif data["description"] and data["description"] not in merged["description"]:
                merged["description"] += f"\n\n[Other Info]: {data['description']}"
            
            merged["sources"].append("descriptions")

        if key in categories:
            data = categories[key]
            if not merged["name"]:
                merged["name"] = data["name"]
            
            if not merged["functions"]:
                merged["functions"] = data["functions"]
            elif data["functions"] and data["functions"] not in merged["functions"]:
                merged["functions"] += f", {data['functions']}"
                
            merged["warnings"] = data["warnings"]
            merged["origin"] = data["origin"]
            merged["charge"] = data["charge"]
            merged["sources"].append("categories")

        if key in bpom_harmful:
            data = bpom_harmful[key]
            if not merged["name"]:
                merged["name"] = data["name"]
            merged["harmful"] = True
            merged["bpom_warning"] = data["bpom_warning"]
            merged["sources"].append("bpom_harmful")
            
        if key in inci_products:
            merged["found_in_products"] = inci_products[key]

        merged_data_list.append(merged)
    
    print(f"Total merged ingredients: {len(merged_data_list)}")

    print(f"Initializing Qdrant Client at {QDRANT_DATA_DIR}")
    os.makedirs(QDRANT_DATA_DIR, exist_ok=True)
    
    client = QdrantClient(path=QDRANT_DATA_DIR)
    
    if client.collection_exists(COLLECTION_NAME):
        print(f"Collection '{COLLECTION_NAME}' already exists. Deleting it to recreate...")
        client.delete_collection(COLLECTION_NAME)

    print(f"Creating collection '{COLLECTION_NAME}'...")
    client.create_collection(
        collection_name=COLLECTION_NAME,
        vectors_config=VectorParams(size=VECTOR_SIZE, distance=Distance.COSINE)
    )
    
    print("Preparing documents for vectorization via Gemini API...")
    points = []
    
    for idx, item in enumerate(merged_data_list, start=1):
        doc_text = f"Ingredient: {item['name']}\n"
        if item.get('rating'):
            doc_text += f"Rating: {item['rating']}\n"
        if item.get('description'):
            doc_text += f"Description: {_clip(item['description'], 300)}\n"
        if item.get('functions'):
            doc_text += f"Functions: {item['functions']}\n"
        if item.get('harmful'):
            doc_text += f"Status: HARMFUL (BPOM Banned)\n"
        if item.get('found_in_products'):
            products_str = ", ".join(item['found_in_products'])
            doc_text += f"Found in products: {products_str}\n"

        print(f"Generating embedding {idx}/{len(merged_data_list)}: {item['name'][:30].encode('ascii', 'ignore').decode('ascii')}")
        try:
            vector = get_embedding(doc_text)
        except Exception as e:
            print(f"Failed to embed {item['name']}: {e}")
            continue

        points.append(
            PointStruct(
                id=idx,
                vector=vector,
                payload=item
            )
        )
        
        # Batch insert to avoid huge memory/API limits
        if len(points) >= 100:
            client.upsert(
                collection_name=COLLECTION_NAME,
                points=points
            )
            print(f"Upserted {idx} points...")
            points = []
            
    if points:
        client.upsert(
            collection_name=COLLECTION_NAME,
            points=points
        )
    
    print(f"Successfully ingested ingredients into Qdrant collection '{COLLECTION_NAME}'.")


if __name__ == "__main__":
    setup_qdrant()
