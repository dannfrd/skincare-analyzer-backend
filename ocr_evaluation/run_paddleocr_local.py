import os
import sys
import time
import json

# Nonaktifkan MKLDNN/oneDNN untuk menghindari bug regresi PIR pada PaddlePaddle 3.3+ (CPU Windows)
os.environ["FLAGS_use_mkldnn"] = "0"
os.environ["PADDLE_PDX_ENABLE_MKLDNN_BYDEFAULT"] = "0"
# Lewati pengecekan koneksi hoster model Baidu untuk mencegah hang saat inisialisasi
os.environ["PADDLE_PDX_DISABLE_MODEL_SOURCE_CHECK"] = "True"

# Setup paths agar bisa mengakses modules di root backend
current_dir = os.path.dirname(os.path.abspath(__file__))
backend_dir = os.path.abspath(os.path.join(current_dir, ".."))
if backend_dir not in sys.path:
    sys.path.insert(0, backend_dir)

try:
    from paddleocr import PaddleOCR
except ImportError as e:
    print(f"[ERROR] Gagal memuat modul PaddleOCR: {e}")
    print("Pastikan Anda menggunakan interpreter Python yang tepat dengan library paddleocr terinstal.")
    exit(1)

def main():
    print("==================================================")
    print("        RUNNER OCR PADDLEOCR MURNI LOKAL          ")
    print("==================================================")
    
    raw_images_dir = os.path.join(current_dir, "dataset", "images_raw")
    if len(sys.argv) > 1:
        for i, arg in enumerate(sys.argv):
            if arg == "--dataset_dir" and i + 1 < len(sys.argv):
                raw_images_dir = sys.argv[i + 1]
            elif not arg.startswith("--") and i > 0 and sys.argv[i-1] != "--dataset_dir":
                raw_images_dir = arg

    paddle_results_dir = os.path.join(current_dir, "results", "paddleocr")
    os.makedirs(paddle_results_dir, exist_ok=True)
    
    if not os.path.exists(raw_images_dir):
        print(f"[ERROR] Folder images tidak ditemukan di: {raw_images_dir}")
        print("Silakan buat folder tersebut terlebih dahulu.")
        return
        
    # Cari semua file gambar pendukung
    image_files = []
    for f in os.listdir(raw_images_dir):
        if f.lower().endswith(('.png', '.jpg', '.jpeg', '.webp', '.bmp')):
            image_files.append(f)
    image_files = sorted(image_files)
            
    if not image_files:
        print("[INFO] Tidak ada file gambar di folder dataset/images_raw/.")
        print("Silakan letakkan foto kemasan skincare di sana terlebih dahulu.")
        print("Gunakan penamaan file sesuai kode sampel, misal: sample_009.jpg")
        return
        
    print(f"[INFO] Menemukan {len(image_files)} file gambar untuk diproses.")
    
    # Inisialisasi PaddleOCR (hanya deteksi + rekognisi menggunakan bahasa Inggris)
    print("  Menginisialisasi model PaddleOCR (Bisa memakan waktu saat download pertama)...")
    try:
        # Nonaktifkan modul document unwarping & orientation classify yang bermasalah di Windows CPU (oneDNN)
        ocr = PaddleOCR(
            use_doc_orientation_classify=False,
            use_doc_unwarping=False,
            use_textline_orientation=True,
            text_det_thresh=0.2,
            text_det_box_thresh=0.5,
            text_det_unclip_ratio=1.8,
            lang='en',
            ocr_version='PP-OCRv4',
            cpu_threads=2,
            enable_mkldnn=False
        )
    except Exception as e:
        print(f"[ERROR] Gagal menginisialisasi PaddleOCR: {e}")
        return

    for filename in image_files:
        sample_name = os.path.splitext(filename)[0]
        if "_" in sample_name:
            parts = sample_name.split("_")
            if len(parts) >= 2 and parts[0] == "sample" and parts[1].isdigit():
                sample_name = f"{parts[0]}_{parts[1]}"
        
        image_path = os.path.join(raw_images_dir, filename)
        output_txt_path = os.path.join(paddle_results_dir, f"{sample_name}.txt")
        output_meta_path = os.path.join(paddle_results_dir, f"{sample_name}_metadata.json")
        
        print(f"\nMemproses {filename} ({sample_name}) dengan PaddleOCR...")
        
        start_time = time.time()
        try:
            result = ocr.predict(image_path)
            lines = []
            if result:
                for res in result:
                    data = res.json if hasattr(res, 'json') else (res if isinstance(res, dict) else None)
                    if isinstance(data, dict):
                        rec_texts = data.get("rec_texts")
                        dt_polys = data.get("dt_polys")
                        if not rec_texts and "res" in data and isinstance(data["res"], dict):
                            rec_texts = data["res"].get("rec_texts")
                            dt_polys = data["res"].get("dt_polys")
                        
                        if rec_texts:
                            if dt_polys and len(dt_polys) == len(rec_texts):
                                try:
                                    paired = sorted(zip(dt_polys, rec_texts), key=lambda x: x[0][0][1] if x[0] and len(x[0]) > 0 else 0)
                                    lines.extend([str(t[1]) for t in paired])
                                except Exception:
                                    lines.extend([str(t) for t in rec_texts])
                            else:
                                lines.extend([str(t) for t in rec_texts])

            extracted_text = "\n".join(lines)
            elapsed_time_ms = int((time.time() - start_time) * 1000)
            
            # Simpan hasil teks OCR
            with open(output_txt_path, "w", encoding="utf-8") as f:
                f.write(extracted_text)
                
            # Simpan metadata waktu pemrosesan
            with open(output_meta_path, "w", encoding="utf-8") as f:
                json.dump({"time_ms": elapsed_time_ms}, f)
                
            print(f"  [SUKSES] Tersimpan ke results/paddleocr/{sample_name}.txt ({elapsed_time_ms} ms)")
            preview = extracted_text.replace('\n', ' ')
            print(f"  [TEKS DETEKSI]: {preview[:150]}...")
        except Exception as e:
            print(f"  [ERROR] Gagal memproses gambar {filename}: {e}")
            
    print("\n==================================================")
    print("Proses Batch PaddleOCR Murni Selesai!")
    print("Silakan jalankan 'python ocr_evaluation/evaluate.py' untuk membandingkan hasil.")
    print("==================================================")

if __name__ == "__main__":
    main()
