# Dataset Information

## Available Datasets

Backend menggunakan 3 dataset utama di folder `data/dataset_scincare/`:

### 1. cosmetic_ingredients_train.csv

**Purpose**: RAG (Retrieval-Augmented Generation) context untuk Gemini AI

**Columns**:
- `ingredient`: Nama ingredient
- `description`: Deskripsi lengkap (fungsi, manfaat, cara kerja, dll)

**Size**: 1000+ ingredients

**Usage**: 
- Digunakan oleh `modules/rag_context.py`
- Di-retrieve saat analisis untuk memberikan context ke AI
- Fuzzy matching dengan threshold 84%

**Example**:
```csv
ingredient,description
Glycerin,"Glycerin is a humectant that helps skin retain moisture..."
Niacinamide,"Niacinamide is a form of vitamin B3 that helps..."
```

### 2. ingredients_category.csv

**Purpose**: Kategori dan fungsi ingredient

**Columns**:
- `ingredient_name`: Nama ingredient
- `function1`: Fungsi utama
- `function2`: Fungsi sekunder
- `warning1`: Peringatan 1
- `warning2`: Peringatan 2
- `ingredient_origin`: Natural/Synthetic
- `ingredient_charge`: Ionik/Non-ionik/Kationik/Anionik

**Size**: 500+ ingredients

**Usage**: 
- Reference untuk kategorisasi ingredient
- Bisa diintegrasikan ke database MySQL

**Example**:
```csv
ingredient_name,function1,function2,warning1,warning2,ingredient_origin,ingredient_charge
"1,2-Hexanediol",Solvent,Preservative Booster,,,Synthetic,Non-ionik
Glycerin,Humectant,Moisturizer,,,Natural,Non-ionik
```

### 3. Database Kosmetik Mengandung Bahan Berbahaya.csv

**Purpose**: Data BPOM tentang ingredient berbahaya

**Source**: Direktorat Standardisasi Obat Tradisional, Suplemen Kesehatan dan Kosmetik

**Usage**:
- Reference untuk warning system
- Bisa diintegrasikan ke expert system

## RAG Configuration

Di `.env`:

```env
# Dataset paths (optional - defaults to data/dataset_scincare/)
RAG_DATASET_DESCRIPTIONS=data/dataset_scincare/cosmetic_ingredients_train.csv
RAG_DATASET_CATEGORIES=data/dataset_scincare/ingredients_category.csv
RAG_DATASET_BPOM=data/dataset_scincare/Database Kosmetik Mengandung Bahan Berbahaya - Direktorat Standardisasi Obat Tradisional, Suplemen Kesehatan dan Kosmetik.csv

# Fuzzy matching threshold (0.0 - 1.0)
# Semakin tinggi = semakin strict
RAG_FUZZY_THRESHOLD=0.84

# Max items yang di-retrieve untuk context
RAG_MAX_CONTEXT_ITEMS=12
```

**Note**: Jika environment variables tidak di-set, akan menggunakan default paths di atas.

## How RAG Works

**Multi-Dataset Retrieval Strategy**:

```python
# 1. Load all 3 datasets (cached)
descriptions = _load_descriptions_dataset()  # 1000+ ingredients
categories = _load_categories_dataset()      # 500+ ingredients
bpom_harmful = _load_bpom_harmful_dataset()  # BPOM data

# 2. Normalize ingredient tokens
normalized_tokens = [_normalize_name(token) for token in ingredient_tokens]

# 3. Match dengan semua 3 datasets
all_keys = set()
all_keys.update(descriptions.keys())
all_keys.update(categories.keys())
all_keys.update(bpom_harmful.keys())

for token in normalized_tokens:
    # Exact match
    if token in all_keys:
        matched_key = token
    # Fuzzy match
    else:
        close_matches = difflib.get_close_matches(
            token, 
            all_keys, 
            n=1, 
            cutoff=0.84
        )
        if close_matches:
            matched_key = close_matches[0]
    
    # 4. Merge data from all 3 datasets
    merged_data = {
        "name": "",
        "description": "",      # from dataset 1
        "functions": "",        # from dataset 2
        "warnings": "",         # from dataset 2
        "origin": "",           # from dataset 2
        "harmful": False,       # from dataset 3
        "bpom_warning": "",     # from dataset 3
        "sources": []           # track which datasets have data
    }
    
    if matched_key in descriptions:
        merged_data["description"] = descriptions[matched_key]["description"]
        merged_data["sources"].append("descriptions")
    
    if matched_key in categories:
        merged_data["functions"] = categories[matched_key]["functions"]
        merged_data["warnings"] = categories[matched_key]["warnings"]
        merged_data["origin"] = categories[matched_key]["origin"]
        merged_data["sources"].append("categories")
    
    if matched_key in bpom_harmful:
        merged_data["harmful"] = True
        merged_data["bpom_warning"] = "BPOM: BAHAN BERBAHAYA/DILARANG"
        merged_data["sources"].append("bpom_harmful")
    
    selected_items.append(merged_data)

# 5. Build comprehensive context string
context = "Dataset context (3 trusted sources):\n"
for item in selected_items:
    parts = []
    if item["description"]:
        parts.append(f"deskripsi: {item['description']}")
    if item["functions"]:
        parts.append(f"fungsi: {item['functions']}")
    if item["warnings"]:
        parts.append(f"⚠️ peringatan: {item['warnings']}")
    if item["harmful"]:
        parts.append(f"🚨 BPOM: BAHAN BERBAHAYA/DILARANG")
    
    sources = ", ".join(item["sources"])
    context += f"- {item['name']} [{sources}]: {' | '.join(parts)}\n"

# 6. Send to Gemini AI with comprehensive context
prompt = f"""
Analyze these ingredients with the following trusted context from 3 sources:

{context}

Ingredients to analyze: {ingredient_list}
"""
```

## Dataset Format Requirements

### For RAG (cosmetic_ingredients_train.csv)

**Required columns**:
- `ingredient` atau `name`: Nama ingredient (required)
- `description`: Deskripsi lengkap (required)

**Optional columns** (akan di-parse dari description jika ada):
- `short_description`
- `what_is_it`
- `what_does_it_do`
- `who_is_it_good_for`
- `who_should_avoid`

**Encoding**: UTF-8 with BOM (UTF-8-sig)

**Format**: CSV with header

## Update Dataset

### Menambah Ingredient Baru

1. Edit `cosmetic_ingredients_train.csv`
2. Tambah baris baru:
```csv
New Ingredient,"Detailed description about the ingredient..."
```
3. Restart backend (cache akan refresh)
4. Test dengan ingredient baru

### Mengubah Threshold

Edit `.env`:
```env
# Lebih strict (hanya exact/near-exact match)
RAG_FUZZY_THRESHOLD=0.90

# Lebih loose (terima match yang lebih jauh)
RAG_FUZZY_THRESHOLD=0.75
```

### Mengubah Max Items

Edit `.env`:
```env
# Lebih banyak context (lebih lambat, lebih lengkap)
RAG_MAX_CONTEXT_ITEMS=20

# Lebih sedikit context (lebih cepat, lebih fokus)
RAG_MAX_CONTEXT_ITEMS=8
```

## Performance

- **Dataset loading**: Cached dengan `@lru_cache`
- **First request**: ~100-200ms (load + match)
- **Subsequent requests**: ~10-20ms (cached)
- **Memory usage**: ~5-10MB per dataset

## Monitoring

Check RAG status di response:

```json
{
  "ai_analysis": {
    "model_output": "...",
    "rag_status": "enabled",
    "rag_items_retrieved": 8
  }
}
```

Jika RAG disabled:
```json
{
  "ai_analysis": {
    "rag_status": "disabled",
    "rag_reason": "dataset_unavailable"
  }
}
```

## Troubleshooting

### RAG tidak retrieve data

1. **Check file exists**:
```bash
ls data/dataset_scincare/cosmetic_ingredients_train.csv
```

2. **Check encoding**:
```bash
file -i data/dataset_scincare/cosmetic_ingredients_train.csv
# Should show: charset=utf-8
```

3. **Check format**:
```python
import csv
with open('data/dataset_scincare/cosmetic_ingredients_train.csv', 'r', encoding='utf-8-sig') as f:
    reader = csv.DictReader(f)
    print(reader.fieldnames)  # Should show: ['ingredient', 'description']
```

4. **Check environment variable**:
```bash
echo $RAG_INGREDIENT_DATASET
```

### Fuzzy match terlalu banyak/sedikit

Adjust threshold di `.env`:
- Terlalu banyak false positive → Naikkan threshold (0.90)
- Terlalu sedikit match → Turunkan threshold (0.75)

### Performance lambat

1. Reduce `RAG_MAX_CONTEXT_ITEMS`
2. Optimize dataset (remove duplicates)
3. Check cache working (should be fast after first request)

## Best Practices

✅ **DO**:
- Keep descriptions concise but informative
- Use UTF-8 encoding
- Include ingredient variations (e.g., "Vitamin C, Ascorbic Acid")
- Update dataset regularly
- Monitor RAG metrics

❌ **DON'T**:
- Don't use special characters in ingredient names
- Don't make descriptions too long (>1000 chars)
- Don't duplicate ingredients
- Don't change column names without updating code
- Don't forget to restart backend after dataset changes

## Future Improvements

- [ ] Support multiple languages
- [ ] Add ingredient synonyms table
- [ ] Implement semantic search (embeddings)
- [ ] Add dataset versioning
- [ ] Implement A/B testing for thresholds
- [ ] Add dataset validation script
- [ ] Create dataset update API

## References

- RAG Implementation: `modules/rag_context.py`
- Gemini Integration: `modules/gemini_ai.py`
- Dataset Location: `data/dataset_scincare/`
