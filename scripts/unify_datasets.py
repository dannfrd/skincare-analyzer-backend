import os
import csv
import shutil
import re
import io
import sys

sys.stdout.reconfigure(encoding='utf-8')

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DATA_DIR = os.path.join(BASE_DIR, "data", "dataset_scincare")

# INCI Paths
INCI_PRODUCTS_PATH = os.path.join(DATA_DIR, "incidecoder_products.csv")
INCI_INGREDIENTS_PATH = os.path.join(DATA_DIR, "incidecoder_ingredients.csv")
INCI_RELATIONS_PATH = os.path.join(DATA_DIR, "incidecoder_product_ingredients.csv")

# Skincarisma Paths
SKINCARISMA_PRODUCTS_PATH = os.path.join(DATA_DIR, "skincarisma_products.csv")
SKINCARISMA_INGREDIENTS_PATH = os.path.join(DATA_DIR, "skincarisma_ingredients.csv")
SKINCARISMA_RELATIONS_PATH = os.path.join(DATA_DIR, "skincarisma_product_ingredients.csv")

def _normalize_name(value: str) -> str:
    """Normalize ingredient name for matching, matching qdrant_setup logic exactly"""
    normalized = re.sub(r"[^A-Za-z0-9\s\-\+\./]", " ", value.upper())
    return re.sub(r"\s+", " ", normalized).strip()

def restore_inci_files():
    print("--- Restoring original INCI database files from backups ---")
    for path in [INCI_PRODUCTS_PATH, INCI_INGREDIENTS_PATH, INCI_RELATIONS_PATH]:
        bak_path = path + ".bak"
        if os.path.exists(bak_path):
            shutil.copy(bak_path, path)
            print(f"Restored: {os.path.basename(bak_path)} -> {os.path.basename(path)}")
        else:
            print(f"Warning: Backup file {bak_path} not found. Cannot restore.")

def main():
    # 1. Restore INCI files so they contain only pure INCI data
    restore_inci_files()
    
    # 2. Check if Skincarisma products file exists
    if not os.path.exists(SKINCARISMA_PRODUCTS_PATH):
        print(f"Error: Skincarisma products file not found at {SKINCARISMA_PRODUCTS_PATH}")
        return
        
    print(f"Generating Skincarisma relational tables from {SKINCARISMA_PRODUCTS_PATH}...")
    
    ingredients = [] # list of dicts: {id, inci_name, rating, functions, description}
    name_to_id = {} # normalized_name -> ingredient_id
    relations = [] # list of dicts: {id, product_id, ingredient_id, ingredient_order}
    
    max_ing_id = 0
    max_rel_id = 0
    
    with open(SKINCARISMA_PRODUCTS_PATH, 'r', encoding='utf-8') as f:
        reader = csv.DictReader(f)
        for row in reader:
            prod_id = row.get("id", "").strip()
            ingredient_raw = row.get("ingredient_raw", "").strip()
            
            if not prod_id or not ingredient_raw:
                continue
                
            # Clean parentheses contents e.g. "Water (Aqua)" -> "Water"
            raw_ingredients_split = [
                re.sub(r"\s*\([^)]*\)", "", part).strip()
                for part in ingredient_raw.split(",")
                if part.strip()
            ]
            
            for order_idx, ing_name in enumerate(raw_ingredients_split, start=1):
                norm_name = _normalize_name(ing_name)
                if not norm_name:
                    continue
                    
                if norm_name in name_to_id:
                    ing_id = name_to_id[norm_name]
                else:
                    max_ing_id += 1
                    ing_id = max_ing_id
                    name_to_id[norm_name] = ing_id
                    ingredients.append({
                        "id": ing_id,
                        "inci_name": ing_name,
                        "rating": "",
                        "functions": "",
                        "description": ""
                    })
                    
                max_rel_id += 1
                relations.append({
                    "id": str(max_rel_id),
                    "product_id": prod_id,
                    "ingredient_id": str(ing_id),
                    "ingredient_order": str(order_idx)
                })
                
    print(f"Generated {len(ingredients)} unique ingredients and {len(relations)} relations for Skincarisma.")
    
    # 3. Save Skincarisma ingredients CSV
    print(f"Writing {len(ingredients)} ingredients to {SKINCARISMA_INGREDIENTS_PATH}...")
    with open(SKINCARISMA_INGREDIENTS_PATH, 'w', newline='', encoding='utf-8') as f:
        f.write("id,inci_name,rating,functions,description;;\n")
        for ing in ingredients:
            output = io.StringIO()
            writer = csv.writer(output, lineterminator="")
            writer.writerow([
                ing["id"],
                ing["inci_name"],
                ing["rating"],
                ing["functions"],
                ing["description"]
            ])
            line = output.getvalue()
            f.write(line + ";;\n")
            
    # 4. Save Skincarisma product-ingredients relations CSV
    print(f"Writing {len(relations)} relations to {SKINCARISMA_RELATIONS_PATH}...")
    with open(SKINCARISMA_RELATIONS_PATH, 'w', newline='', encoding='utf-8') as f:
        writer = csv.DictWriter(f, fieldnames=['id', 'product_id', 'ingredient_id', 'ingredient_order'])
        writer.writeheader()
        for rel in relations:
            writer.writerow(rel)
            
    print("Decoupled Skincarisma relational database generated successfully!")

if __name__ == "__main__":
    main()
