import os
import sys
if hasattr(sys.stdout, 'reconfigure'):
    sys.stdout.reconfigure(encoding='utf-8', errors='replace')
import argparse
import csv
import re
import difflib
from typing import List, Dict, Set, Tuple

# Pastikan path root project bisa diakses untuk import modul
PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

try:
    from modules.text_cleaning import clean_text_pipeline
except ImportError:
    # Fallback sederhana jika dijalankan terisolasi
    def clean_text_pipeline(text: str, *, use_ai: bool = False) -> List[str]:
        text = text.strip().upper()
        text = re.sub(r'(?i)INGREDIENTS?\s*[:\-]?\s*', '', text)
        raw_list = [item.strip() for item in re.split(r'[,;.\n]', text)]
        cleaned = []
        seen = set()
        for item in raw_list:
            norm = re.sub(r'\s+', ' ', item).strip(' .-')
            if len(norm) > 1 and not norm.isnumeric() and norm not in seen:
                seen.add(norm)
                cleaned.append(norm)
        return cleaned

from ocr_evaluation.evaluate import SAMPLE_BRANDS


def normalize_ing(s: str) -> str:
    """Membersihkan teks bahan kosmetik untuk pencocokan inti."""
    cleaned = re.sub(r'\s*\([^)]*\)', '', s).strip().upper()
    cleaned = re.sub(r'\s+', ' ', cleaned)
    return cleaned if len(cleaned) > 1 else s.strip().upper()


def analyze_sample_errors(gt_ingredients: List[str], ocr_tokens: List[str]) -> Dict:
    """
    Menganalisis detail pencocokan bahan, mengelompokkan mana yang matched, miss, dan false positive,
    serta memberikan estimasi penyebab miss.
    """
    gt_norm_map = {normalize_ing(gt): gt for gt in gt_ingredients if gt.strip()}
    gt_norm_list = list(gt_norm_map.keys())
    
    ocr_norm_map = {normalize_ing(ocr): ocr for ocr in ocr_tokens if ocr.strip()}
    ocr_norm_list = list(ocr_norm_map.keys())

    matched_pairs = [] # List of (gt_original, ocr_original, match_type)
    matched_gt_norms = set()
    matched_ocr_norms = set()

    # 1. Exact & Substring & Fuzzy Matching
    for o_norm in ocr_norm_list:
        if o_norm in matched_ocr_norms:
            continue
        
        # Cek exact
        if o_norm in gt_norm_map and o_norm not in matched_gt_norms:
            matched_pairs.append((gt_norm_map[o_norm], ocr_norm_map[o_norm], "Exact"))
            matched_gt_norms.add(o_norm)
            matched_ocr_norms.add(o_norm)
            continue
        
        # Cek Fuzzy difflib cutoff 0.72
        matches = difflib.get_close_matches(o_norm, [g for g in gt_norm_list if g not in matched_gt_norms], n=1, cutoff=0.72)
        if matches:
            matched_pairs.append((gt_norm_map[matches[0]], ocr_norm_map[o_norm], "Fuzzy (0.72+)"))
            matched_gt_norms.add(matches[0])
            matched_ocr_norms.add(o_norm)
            continue
            
        # Cek Substring untuk bahan panjang (>= 4 karakter)
        for g_norm in gt_norm_list:
            if g_norm in matched_gt_norms:
                continue
            if len(o_norm) >= 4 and len(g_norm) >= 4:
                if o_norm in g_norm or g_norm in o_norm:
                    matched_pairs.append((gt_norm_map[g_norm], ocr_norm_map[o_norm], "Substring"))
                    matched_gt_norms.add(g_norm)
                    matched_ocr_norms.add(o_norm)
                    break

    # 2. Identifikasi Missed Ingredients (False Negatives)
    missed_gt_list = [gt for norm, gt in gt_norm_map.items() if norm not in matched_gt_norms]
    
    # 3. Identifikasi False Positives (Token salah yang terdeteksi OCR)
    false_positives_ocr = [ocr for norm, ocr in ocr_norm_map.items() if norm not in matched_ocr_norms]

    # 4. Analisis & Kategorisasi Penyebab Miss
    missed_with_reasons = []
    total_gt = len(gt_ingredients) if len(gt_ingredients) > 0 else 1
    
    for gt_item in missed_gt_list:
        g_norm = normalize_ing(gt_item)
        reason = "Gagal terdeteksi oleh OCR / terpotong"
        
        # Cek apakah ada kata di OCR yang mirip (cutoff 0.45 - 0.71) -> Typo berat
        weak_matches = difflib.get_close_matches(g_norm, ocr_norm_list, n=1, cutoff=0.45)
        if weak_matches:
            reason = f"OCR Typo / Salah Karakter (Terbaca sebagai: '{ocr_norm_map[weak_matches[0]]}')"
        else:
            # Cek posisi di daftar asli untuk mendeteksi terpotong (Cut-off)
            try:
                idx = gt_ingredients.index(gt_item)
                if idx < total_gt * 0.2:
                    reason = "Terpotong (Cut-off) di Bagian Atas Kemasan"
                elif idx > total_gt * 0.8:
                    reason = "Terpotong (Cut-off) di Bagian Bawah Kemasan"
            except ValueError:
                pass
                
        missed_with_reasons.append(f"{gt_item} [{reason}]")

    return {
        "total_gt": len(gt_ingredients),
        "total_ocr": len(ocr_tokens),
        "matched_count": len(matched_pairs),
        "missed_count": len(missed_gt_list),
        "fp_count": len(false_positives_ocr),
        "matched_pairs": matched_pairs,
        "missed_gt_list": missed_gt_list,
        "missed_with_reasons": missed_with_reasons,
        "false_positives_ocr": false_positives_ocr
    }


def run_error_analysis(gt_dir: str, results_dir: str, engine: str, output_csv: str, skenario_label: str):
    print("==================================================")
    print(f"  SISTEM ANALISIS ERROR & MISS BAHAN ({skenario_label})")
    print("==================================================")
    print(f"[INFO] Ground Truth Dir: {gt_dir}")
    print(f"[INFO] OCR Results Dir: {results_dir}")
    print(f"[INFO] Target Engine(s): {engine.upper()}\n")

    if not os.path.exists(gt_dir) or not os.path.exists(results_dir):
        print("[ERROR] Direktori Ground Truth atau Results tidak ditemukan.")
        return

    # Cari file _ingredients.txt di gt_dir
    sample_names = set()
    for fname in os.listdir(gt_dir):
        if fname.endswith("_ingredients.txt"):
            sname = fname.replace("_ingredients.txt", "")
            sample_names.add(sname)

    sample_names = sorted(list(sample_names))
    print(f"[INFO] Ditemukan {len(sample_names)} sampel pengujian: {', '.join(sample_names)}\n")

    if engine.lower() == "all":
        engines_to_test = [e for e in ["paddleocr", "mlkit", "chandra", "tesseract"] if os.path.isdir(os.path.join(results_dir, e))]
        if not engines_to_test:
            engines_to_test = ["paddleocr"]
    else:
        engines_to_test = [e.strip() for e in engine.split(",")]

    rows_to_save = []

    for eng in engines_to_test:
        engine_dir = os.path.join(results_dir, eng)
        if not os.path.exists(engine_dir):
            continue

        print("=" * 65)
        print(f" >>> ANALISIS ENGINE: {eng.upper()}")
        print("=" * 65)

        for sname in sample_names:
            brand_name = SAMPLE_BRANDS.get(sname, sname)
            gt_file = os.path.join(gt_dir, f"{sname}_ingredients.txt")
            ocr_file = os.path.join(engine_dir, f"{sname}.txt")

            # Baca GT
            with open(gt_file, "r", encoding="utf-8") as f:
                gt_text = f.read()
            gt_ingredients = [item.strip() for item in re.split(r'[,;\n]', gt_text) if item.strip()]

            # Baca OCR
            if not os.path.exists(ocr_file):
                continue

            with open(ocr_file, "r", encoding="utf-8") as f:
                ocr_text = f.read()
            ocr_tokens = clean_text_pipeline(ocr_text, use_ai=False)

            # Analisis error
            analysis = analyze_sample_errors(gt_ingredients, ocr_tokens)

            # Cetak ke terminal
            print(f"[PRODUK] {brand_name} ({sname})")
            print(f"   [STATISTIK] {analysis['matched_count']}/{analysis['total_gt']} Berhasil Dikenali | "
                  f"Miss: {analysis['missed_count']} bahan | False Positives (Noise): {analysis['fp_count']} token")
            
            if analysis["missed_gt_list"]:
                print("   [MISS] BAHAN YANG MISS / TERLEWAT (False Negatives):")
                for m_item in analysis["missed_with_reasons"]:
                    print(f"      - {m_item}")
            else:
                print("   [SUKSES] SEMUA BAHAN ASLI BERHASIL DIKENALI SECARA SEMPURNA (100% MATCH)!")

            if analysis["false_positives_ocr"]:
                print("   [NOISE] TOKEN SALAH / NOISE OCR (False Positives):")
                print(f"      -> {', '.join(analysis['false_positives_ocr'][:8])}" + 
                      ("..." if len(analysis['false_positives_ocr']) > 8 else ""))
            print("-" * 65)

            rows_to_save.append({
                "Skenario": skenario_label,
                "Kode Sample": sname,
                "Nama Produk": brand_name,
                "Engine OCR": eng.upper(),
                "Total Bahan Asli (GT)": analysis["total_gt"],
                "Total Berhasil Dikenali": analysis["matched_count"],
                "Total Miss / Terlewat": analysis["missed_count"],
                "Total False Positives (Noise)": analysis["fp_count"],
                "Daftar Bahan MISS (False Negatives)": " | ".join(analysis["missed_gt_list"]),
                "Detail Penyebab MISS": " || ".join(analysis["missed_with_reasons"]),
                "Daftar Token Salah (False Positives)": " | ".join(analysis["false_positives_ocr"])
            })

    # Simpan CSV
    if rows_to_save:
        os.makedirs(os.path.dirname(output_csv), exist_ok=True)
        headers = list(rows_to_save[0].keys())
        with open(output_csv, "w", encoding="utf-8", newline="") as f:
            writer = csv.DictWriter(f, fieldnames=headers)
            writer.writeheader()
            writer.writerows(rows_to_save)
        print(f"\n[SUKSES] Laporan analisis miss bahan berhasil diekspor ke: {output_csv}")


def main():
    parser = argparse.ArgumentParser(description="Analisis Error dan Miss Bahan Skincare OCR")
    parser.add_argument("--skenario", type=int, choices=[1, 2], default=2, help="Pilih Skenario 1 (Single) atau 2 (Multiple)")
    parser.add_argument("--engine", type=str, default="all", help="Engine OCR (default: all)")
    parser.add_argument("--gt_dir", type=str, default="", help="Override path Ground Truth directory")
    parser.add_argument("--results_dir", type=str, default="", help="Override path OCR Results directory")
    parser.add_argument("--output_csv", type=str, default="", help="Override path output CSV")

    args = parser.parse_args()

    if args.skenario == 1:
        gt_dir = args.gt_dir or os.path.join("ocr_evaluation", "dataset", "ground_truth")
        results_dir = args.results_dir or os.path.join("ocr_evaluation", "results")
        output_csv = args.output_csv or os.path.join("ocr_evaluation", "results", "missed_ingredients_skenario_1.csv")
        skenario_label = "Skenario 1 (Single Product / Multi Trial)"
    else:
        gt_dir = args.gt_dir or os.path.join("ocr_evaluation", "dataset", "skenario_2_multi_product")
        results_dir = args.results_dir or os.path.join("ocr_evaluation", "results_skenario_2")
        output_csv = args.output_csv or os.path.join("ocr_evaluation", "results", "missed_ingredients_skenario_2.csv")
        skenario_label = "Skenario 2 (Multiple Products / Multi Brand)"

    run_error_analysis(gt_dir, results_dir, args.engine, output_csv, skenario_label)


if __name__ == "__main__":
    main()
