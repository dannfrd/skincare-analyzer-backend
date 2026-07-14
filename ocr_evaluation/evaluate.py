import os
import sys
import re
import csv
import json
import difflib

# Menambahkan root direktori backend ke dalam sys.path agar bisa memuat modul text_cleaning
current_dir = os.path.dirname(os.path.abspath(__file__))
backend_dir = os.path.abspath(os.path.join(current_dir, ".."))
if backend_dir not in sys.path:
    sys.path.insert(0, backend_dir)

try:
    # Memuat pipeline pembersihan teks yang digunakan oleh aplikasi
    from modules.text_cleaning import clean_text_pipeline
    has_system_cleaner = True
except ImportError as e:
    has_system_cleaner = False
    # Fallback jika dijalankan di luar lingkungan aplikasi backend
    def clean_text_pipeline(text, *, use_ai=False):
        text = text.upper()
        # Normalisasi spasi dan baris baru
        text = re.sub(r'\s+', ' ', text)
        # Pisahkan berdasarkan koma atau titik koma
        raw_ingredients = [item.strip() for item in re.split(r'[,;]', text)]
        return [i for i in raw_ingredients if len(i) > 1 and not i.isnumeric()]

def levenshtein_distance(seq1, seq2):
    """
    Menghitung jarak edit Levenshtein antara dua urutan (string atau list).
    Digunakan untuk perhitungan CER (tingkat karakter) dan WER (tingkat kata).
    """
    m, n = len(seq1), len(seq2)
    dp = [[0] * (n + 1) for _ in range(m + 1)]
    for i in range(m + 1):
        dp[i][0] = i
    for j in range(n + 1):
        dp[0][j] = j
        
    for i in range(1, m + 1):
        for j in range(1, n + 1):
            if seq1[i-1] == seq2[j-1]:
                dp[i][j] = dp[i-1][j-1]
            else:
                dp[i][j] = min(
                    dp[i-1][j] + 1,    # Deletion
                    dp[i][j-1] + 1,    # Insertion
                    dp[i-1][j-1] + 1   # Substitution
                )
    return dp[m][n]

def calculate_cer(gt_text, ocr_text):
    """Menghitung Character Error Rate (CER)."""
    gt_clean = gt_text.strip().lower()
    ocr_clean = ocr_text.strip().lower()
    if not gt_clean:
        return 1.0 if ocr_clean else 0.0
    dist = levenshtein_distance(gt_clean, ocr_clean)
    return dist / len(gt_clean)

def calculate_wer(gt_text, ocr_text):
    """Menghitung Word Error Rate (WER)."""
    # Tokenisasi kata sederhana (mengabaikan spasi ganda)
    gt_words = [w.lower() for w in gt_text.split() if w]
    ocr_words = [w.lower() for w in ocr_text.split() if w]
    if not gt_words:
        return 1.0 if ocr_words else 0.0
    dist = levenshtein_distance(gt_words, ocr_words)
    return dist / len(gt_words)

def evaluate_ingredient_matching(gt_ingredients, ocr_tokens):
    """
    Menghitung Precision, Recall, dan F1-Score untuk pencocokan bahan kosmetik.
    Mendukung pencocokan persis (Exact) dan pencocokan toleran (Fuzzy).
    """
    gt_set = set(item.upper() for item in gt_ingredients if item.strip())
    ocr_set = set(item.upper() for item in ocr_tokens if item.strip())
    
    if not gt_set:
        return {
            "exact": {"precision": 0.0, "recall": 0.0, "f1": 0.0, "tp": 0, "fp": 0, "fn": 0},
            "fuzzy": {"precision": 0.0, "recall": 0.0, "f1": 0.0, "tp": 0, "fp": 0, "fn": 0}
        }
        
    # --- 1. Exact Match Evaluation ---
    exact_tp = len(ocr_set.intersection(gt_set))
    exact_fp = len(ocr_set - gt_set)
    exact_fn = len(gt_set - ocr_set)
    
    exact_precision = exact_tp / len(ocr_set) if len(ocr_set) > 0 else 0.0
    exact_recall = exact_tp / len(gt_set) if len(gt_set) > 0 else 0.0
    exact_f1 = (2 * exact_precision * exact_recall / (exact_precision + exact_recall)) if (exact_precision + exact_recall) > 0 else 0.0
    
    # --- 2. Fuzzy Match Evaluation (Toleransi 72% & substring matching untuk INCI) ---
    def normalize_ing(s):
        # Hapus keterangan dalam kurung seperti (WATER) atau (CI 77891) untuk mencocokkan inti bahan
        cleaned = re.sub(r'\s*\([^)]*\)', '', s).strip().upper()
        return cleaned if len(cleaned) > 1 else s.strip().upper()

    gt_norm_map = {normalize_ing(gt): gt for gt in gt_set}
    gt_norm_list = list(gt_norm_map.keys())

    fuzzy_tp = 0
    matched_gt = set()
    
    for token in ocr_set:
        token_norm = normalize_ing(token)
        # 1. Cek difflib close matches dengan cutoff 0.72
        matches = difflib.get_close_matches(token_norm, gt_norm_list, n=1, cutoff=0.72)
        if matches:
            fuzzy_tp += 1
            matched_gt.add(gt_norm_map[matches[0]])
        else:
            # 2. Substring check jika token atau gt cukup panjang (>= 4 karakter)
            found_sub = False
            for g_norm in gt_norm_list:
                if len(token_norm) >= 4 and len(g_norm) >= 4:
                    if token_norm in g_norm or g_norm in token_norm:
                        fuzzy_tp += 1
                        matched_gt.add(gt_norm_map[g_norm])
                        found_sub = True
                        break
            
    fuzzy_fp = len(ocr_set) - fuzzy_tp
    fuzzy_fn = len(gt_set) - len(matched_gt)
    
    fuzzy_precision = fuzzy_tp / len(ocr_set) if len(ocr_set) > 0 else 0.0
    fuzzy_recall = len(matched_gt) / len(gt_set) if len(gt_set) > 0 else 0.0
    fuzzy_f1 = (2 * fuzzy_precision * fuzzy_recall / (fuzzy_precision + fuzzy_recall)) if (fuzzy_precision + fuzzy_recall) > 0 else 0.0
    
    return {
        "exact": {
            "precision": exact_precision,
            "recall": exact_recall,
            "f1": exact_f1,
            "tp": exact_tp,
            "fp": exact_fp,
            "fn": exact_fn
        },
        "fuzzy": {
            "precision": fuzzy_precision,
            "recall": fuzzy_recall,
            "f1": fuzzy_f1,
            "tp": fuzzy_tp,
            "fp": fuzzy_fp,
            "fn": fuzzy_fn
        }
    }

SAMPLE_BRANDS = {
    "sample_001": "Custom Formula",
    "sample_002": "Dermalogica",
    "sample_003": "NIOD",
    "sample_004": "Drunk Elephant",
    "sample_005": "Drunk Elephant",
    "sample_006": "Trilogy",
    "sample_007": "Mario Badescu",
    "sample_008": "Super Facialist",
    "sample_009": "The Ordinary",
    "sample_010": "The Organic Pharmacy",
    "sample_011": "Geek & Gorgeous",
    "sample_012": "Maybelline New York",
    "sample_013": "Maybelline",
    "sample_014": "Marcelle",
    "sample_015": "Celimax",
    "sample_016": "Manucurist",
    "sample_017": "The Ordinary",
    "g2g_cleanser": "G2G Cleanser",
    "sunscreen_emina": "Sunscreen Emina",
    "exfoliasi_skintific": "Exfoliasi Skintific",
    "cleanser_panthenol": "Facial Wash Scora",
    "lipcare_madame_gie": "Lipcare Madame Gie",
    "masker_camille": "Masker Camille",
    "masker_komedo": "Masker Hidung Komedo",
    "facial_wash_kahf": "Facial Wash Kahf",
    "facial_wash_g2g": "Facial Wash G2G",
    "wardah_face_mist": "Wardah Face Mist",
}

def main():
    print("==================================================")
    print("        SISTEM EVALUASI AKURASI OCR               ")
    print("==================================================")
    if has_system_cleaner:
        print("[INFO] Menggunakan TextCleaner sistem backend.")
    else:
        print("[INFO] Menggunakan TextCleaner fallback lokal.")
        
    dataset_dir = os.path.join(current_dir, "dataset")
    gt_dir = os.path.join(dataset_dir, "ground_truth")
    results_dir = os.path.join(current_dir, "results")
    output_csv = None
    engines = ["chandra", "tesseract", "mlkit", "paddleocr"]
    
    product_name = None
    if len(sys.argv) > 1:
        for i, arg in enumerate(sys.argv):
            if arg == "--engine" and i + 1 < len(sys.argv):
                engines = [sys.argv[i + 1].lower()]
            elif arg == "--gt_dir" and i + 1 < len(sys.argv):
                gt_dir = sys.argv[i + 1]
            elif arg == "--results_dir" and i + 1 < len(sys.argv):
                results_dir = sys.argv[i + 1]
            elif arg == "--product_name" and i + 1 < len(sys.argv):
                product_name = sys.argv[i + 1]
            elif arg == "--output_csv" and i + 1 < len(sys.argv):
                output_csv = sys.argv[i + 1]

    if not os.path.exists(gt_dir):
        print(f"[ERROR] Folder Ground Truth tidak ditemukan di: {gt_dir}")
        return
        
    # Ambil sampel pengujian (file *.txt yang bukan *_ingredients.txt)
    samples = []
    for file in sorted(os.listdir(gt_dir)):
        if file.endswith(".txt") and not file.endswith("_ingredients.txt"):
            samples.append(file[:-4]) # Ambil nama filenya saja (misal sample_001)
            
    if not samples:
        print("[WARNING] Tidak ada sampel pengujian di folder Ground Truth.")
        return
        
    print(f"[INFO] Ditemukan {len(samples)} sampel pengujian: {', '.join(samples)}")
    print(f"[INFO] Mengevaluasi engine: {', '.join(engines)}")
    rows_to_save = []
    
    for sample in samples:
        if product_name:
            brand_name = f"{product_name} ({sample})"
        else:
            brand_name = SAMPLE_BRANDS.get(sample, sample)
        print(f"\nEvaluating {sample} ({brand_name})...")
        
        # 1. Load Ground Truth
        gt_text_path = os.path.join(gt_dir, f"{sample}.txt")
        gt_ing_path = os.path.join(gt_dir, f"{sample}_ingredients.txt")
        
        with open(gt_text_path, "r", encoding="utf-8") as f:
            gt_text = f.read()
            
        gt_ingredients = []
        if os.path.exists(gt_ing_path):
            with open(gt_ing_path, "r", encoding="utf-8") as f:
                content = f.read()
                gt_ingredients = [item.strip().upper() for item in re.split(r'[,;\n]', content) if item.strip()]
        else:
            print(f"[WARNING] File ingredient ground truth tidak ditemukan untuk {sample}")
            
        # 2. Evaluasi untuk setiap engine OCR
        for engine in engines:
            engine_result_dir = os.path.join(results_dir, engine)
            ocr_file_path = os.path.join(engine_result_dir, f"{sample}.txt")
            metadata_file_path = os.path.join(engine_result_dir, f"{sample}_metadata.json")
            
            if not os.path.exists(ocr_file_path):
                # Lewati jika engine ini belum diuji untuk sampel ini
                continue
                
            with open(ocr_file_path, "r", encoding="utf-8") as f:
                ocr_text = f.read()
                
            # Baca metadata waktu eksekusi jika ada
            exec_time_ms = "N/A"
            if os.path.exists(metadata_file_path):
                try:
                    with open(metadata_file_path, "r", encoding="utf-8") as f:
                        meta = json.load(f)
                        exec_time_ms = meta.get("time_ms", "N/A")
                except Exception:
                    pass
            
            # Hitung CER dan WER
            cer = calculate_cer(gt_text, ocr_text)
            wer = calculate_wer(gt_text, ocr_text)
            
            # Ekstrak token ingredient dari OCR menggunakan pipeline backend
            ocr_tokens = clean_text_pipeline(ocr_text, use_ai=False)
            
            # Hitung akurasi pencocokan
            match_stats = evaluate_ingredient_matching(gt_ingredients, ocr_tokens)
            
            # Simpan hasil untuk CSV
            rows_to_save.append({
                "Sample": brand_name,
                "Engine": engine,
                "CER (%)": f"{cer*100:.2f}%",
                "WER (%)": f"{wer*100:.2f}%",
                "Exact Match Precision (%)": f"{match_stats['exact']['precision']*100:.2f}%",
                "Exact Match Recall (%)": f"{match_stats['exact']['recall']*100:.2f}%",
                "Exact Match F1 (%)": f"{match_stats['exact']['f1']*100:.2f}%",
                "Fuzzy Match Precision (%)": f"{match_stats['fuzzy']['precision']*100:.2f}%",
                "Fuzzy Match Recall (%)": f"{match_stats['fuzzy']['recall']*100:.2f}%",
                "Fuzzy Match F1 (%)": f"{match_stats['fuzzy']['f1']*100:.2f}%",
                "Execution Time (ms)": exec_time_ms,
                "Total GT Ingredients": len(gt_ingredients),
                "Total OCR Tokens Detected": len(ocr_tokens)
            })
            
            # Cetak ringkasan singkat ke konsol
            print(f"  -> Engine: {engine.upper()}")
            print(f"     [Teks] CER: {cer*100:.2f}% | WER: {wer*100:.2f}% | Waktu: {exec_time_ms} ms")
            print(f"     [Exact Ingredient] Precision: {match_stats['exact']['precision']*100:.1f}% | Recall: {match_stats['exact']['recall']*100:.1f}% | F1: {match_stats['exact']['f1']*100:.1f}%")
            print(f"     [Fuzzy Ingredient] Precision: {match_stats['fuzzy']['precision']*100:.1f}% | Recall: {match_stats['fuzzy']['recall']*100:.1f}% | F1: {match_stats['fuzzy']['f1']*100:.1f}%")
            if len(ocr_tokens) <= 3:
                print(f"     [DEBUG] Token yang diekstrak: {ocr_tokens}")
            
    # Simpan ke CSV
    append_mode = "--append" in sys.argv
    csv_file_path = output_csv if output_csv else os.path.join(results_dir, "summary_results.csv")
    if rows_to_save:
        headers = list(rows_to_save[0].keys())
        existing_rows = []
        file_exists = os.path.exists(csv_file_path) and os.path.getsize(csv_file_path) > 10
        
        if append_mode and file_exists:
            with open(csv_file_path, "r", encoding="utf-8") as f:
                reader = csv.DictReader(f)
                headers = reader.fieldnames or headers
                for row in reader:
                    existing_rows.append(row)
            
            # Upsert (Replace if Sample + Engine matches, else append)
            new_map = {(r["Sample"], r["Engine"]): r for r in rows_to_save}
            updated_rows = []
            seen_keys = set()
            for er in existing_rows:
                key = (er.get("Sample"), er.get("Engine"))
                if key in new_map:
                    updated_rows.append(new_map[key])
                    seen_keys.add(key)
                else:
                    updated_rows.append(er)
            for r in rows_to_save:
                key = (r.get("Sample"), r.get("Engine"))
                if key not in seen_keys:
                    updated_rows.append(r)
            final_rows = updated_rows
            mode_desc = "upsert/append"
        else:
            final_rows = rows_to_save
            mode_desc = "overwrite"

        with open(csv_file_path, "w", encoding="utf-8", newline="") as f:
            writer = csv.DictWriter(f, fieldnames=headers)
            writer.writeheader()
            writer.writerows(final_rows)
        print(f"\n[SUKSES] Hasil evaluasi detail berhasil disimpan ke: {csv_file_path} (mode: {mode_desc})")
    else:
        print("\n[WARNING] Tidak ada hasil pengujian yang dievaluasi.")

if __name__ == "__main__":
    main()
