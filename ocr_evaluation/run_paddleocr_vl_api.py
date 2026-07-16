import os
import sys
import time
import json

# Setup paths agar bisa mengakses modules di root backend
current_dir = os.path.dirname(os.path.abspath(__file__))
backend_dir = os.path.abspath(os.path.join(current_dir, ".."))
if backend_dir not in sys.path:
    sys.path.insert(0, backend_dir)

try:
    from modules.paddleocr_service import PaddleOCRVLAPIProcessor
except ImportError as e:
    print(f"[ERROR] Gagal memuat modul PaddleOCRVLAPIProcessor: {e}")
    exit(1)

def main():
    print("==================================================")
    print("      RUNNER OCR PADDLEOCR-VL-1.6 CLOUD API       ")
    print("==================================================")
    
    raw_images_dir = os.path.join(current_dir, "dataset", "images_raw")
    save_layout_images = False

    if len(sys.argv) > 1:
        for i, arg in enumerate(sys.argv):
            if arg == "--dataset_dir" and i + 1 < len(sys.argv):
                raw_images_dir = sys.argv[i + 1]
            elif arg in ("--save_layout", "--save_images"):
                save_layout_images = True
            elif not arg.startswith("--") and i > 0 and sys.argv[i-1] != "--dataset_dir":
                raw_images_dir = arg

    paddle_vl_results_dir = os.path.join(current_dir, "results", "paddleocr_vl")
    os.makedirs(paddle_vl_results_dir, exist_ok=True)
    
    if not os.path.exists(raw_images_dir):
        print(f"[ERROR] Folder images tidak ditemukan di: {raw_images_dir}")
        return
        
    image_files = [
        f for f in sorted(os.listdir(raw_images_dir))
        if f.lower().endswith(('.png', '.jpg', '.jpeg', '.webp', '.bmp'))
    ]
            
    if not image_files:
        print("[INFO] Tidak ada file gambar di folder dataset/images_raw/.")
        return
        
    print(f"[INFO] Menemukan {len(image_files)} file gambar untuk diproses dengan API PaddleOCR-VL-1.6.")
    
    processor = PaddleOCRVLAPIProcessor()
    print(f"  Token API  : {processor.token[:8]}...{processor.token[-4:]}")
    print(f"  Model API  : {processor.model}")
    print(f"  Endpoint   : {processor.job_url}")

    for filename in image_files:
        sample_name = os.path.splitext(filename)[0]
        if "_" in sample_name:
            parts = sample_name.split("_")
            if len(parts) >= 2 and parts[0] == "sample" and parts[1].isdigit():
                sample_name = f"{parts[0]}_{parts[1]}"
        
        image_path = os.path.join(raw_images_dir, filename)
        output_txt_path = os.path.join(paddle_vl_results_dir, f"{sample_name}.txt")
        output_meta_path = os.path.join(paddle_vl_results_dir, f"{sample_name}_metadata.json")
        layout_save_dir = os.path.join(paddle_vl_results_dir, f"{sample_name}_layout") if save_layout_images else None
        
        print(f"\nMemproses {filename} ({sample_name}) ke Cloud API PaddleOCR-VL-1.6...")
        
        start_time = time.time()
        try:
            extracted_text = processor.extract_text(
                image_path,
                save_layout_dir=layout_save_dir,
                sample_prefix=sample_name
            )
            elapsed_time_ms = int((time.time() - start_time) * 1000)
            
            # Simpan hasil teks OCR
            with open(output_txt_path, "w", encoding="utf-8") as f:
                f.write(extracted_text)
                
            # Simpan metadata waktu pemrosesan
            with open(output_meta_path, "w", encoding="utf-8") as f:
                json.dump({
                    "time_ms": elapsed_time_ms,
                    "engine": "paddleocr_vl",
                    "model": processor.model
                }, f)
                
            print(f"  [SUKSES] Tersimpan ke results/paddleocr_vl/{sample_name}.txt ({elapsed_time_ms} ms)")
            preview = extracted_text.replace('\n', ' ')
            print(f"  [TEKS DETEKSI]: {preview[:150]}...")
        except Exception as e:
            print(f"  [ERROR] Gagal memproses gambar {filename}: {e}")
            
    print("\n==================================================")
    print("Proses Batch PaddleOCR-VL API Selesai!")
    print("Silakan jalankan 'python ocr_evaluation/evaluate.py' untuk membandingkan akurasi.")
    print("==================================================")

if __name__ == "__main__":
    main()
