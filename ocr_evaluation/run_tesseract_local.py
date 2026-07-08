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
    # Memanggil modul preprocessing OpenCV dan OCR Tesseract bawaan backend
    from modules.preprocessing import preprocess_image
    from modules.ocr import extract_text_from_image
except ImportError as e:
    print(f"[ERROR] Gagal memuat modul backend: {e}")
    print("Pastikan Anda menjalankan skrip ini dari lingkungan virtual env yang tepat.")
    exit(1)

def main():
    print("==================================================")
    print("        RUNNER OCR TESSERACT MURNI LOKAL          ")
    print("==================================================")
    
    raw_images_dir = os.path.join(current_dir, "dataset", "images_raw")
    tess_results_dir = os.path.join(current_dir, "results", "tesseract")
    os.makedirs(tess_results_dir, exist_ok=True)
    
    if not os.path.exists(raw_images_dir):
        print(f"[ERROR] Folder images_raw tidak ditemukan di: {raw_images_dir}")
        print("Silakan buat folder tersebut terlebih dahulu.")
        return
        
    # Cari semua file gambar pendukung
    image_files = []
    for f in os.listdir(raw_images_dir):
        if f.lower().endswith(('.png', '.jpg', '.jpeg', '.webp', '.bmp')):
            image_files.append(f)
            
    if not image_files:
        print("[INFO] Tidak ada file gambar di folder dataset/images_raw/.")
        print("Silakan letakkan foto kemasan skincare di sana terlebih dahulu.")
        print("Gunakan penamaan file sesuai kode sampel, misal: sample_009.jpg")
        return
        
    print(f"[INFO] Menemukan {len(image_files)} file gambar untuk diproses.")
    
    for filename in image_files:
        # Cari nama sampel (misal sample_009.jpg -> sample_009)
        sample_name = os.path.splitext(filename)[0]
        # Antisipasi jika nama file panjang (misal sample_009_botol.jpg)
        if "_" in sample_name:
            parts = sample_name.split("_")
            if len(parts) >= 2 and parts[0] == "sample" and parts[1].isdigit():
                sample_name = f"{parts[0]}_{parts[1]}"
        
        image_path = os.path.join(raw_images_dir, filename)
        output_txt_path = os.path.join(tess_results_dir, f"{sample_name}.txt")
        output_meta_path = os.path.join(tess_results_dir, f"{sample_name}_metadata.json")
        
        print(f"\nMemproses {filename} ({sample_name})...")
        
        start_time = time.time()
        try:
            # 1. Jalankan preprocessing OpenCV
            print("  [1/2] Melakukan Image Preprocessing (Grayscale + Thresholding)...")
            processed_image = preprocess_image(image_path)
            
            # 2. Jalankan OCR Tesseract
            print("  [2/2] Mengekstrak teks menggunakan Tesseract OCR...")
            extracted_text = extract_text_from_image(processed_image)
            
            elapsed_time_ms = int((time.time() - start_time) * 1000)
            
            # Simpan hasil teks OCR
            with open(output_txt_path, "w", encoding="utf-8") as f:
                f.write(extracted_text)
                
            # Simpan metadata waktu pemrosesan
            with open(output_meta_path, "w", encoding="utf-8") as f:
                json.dump({"time_ms": elapsed_time_ms}, f)
                
            print(f"  [SUKSES] Tersimpan ke results/tesseract/{sample_name}.txt ({elapsed_time_ms} ms)")
        except Exception as e:
            print(f"  [ERROR] Gagal memproses gambar {filename}: {e}")
            
    print("\n==================================================")
    print("Proses Batch Tesseract Murni Selesai!")
    print("Silakan jalankan 'python ocr_evaluation/evaluate.py' untuk membandingkan hasil.")
    print("==================================================")

if __name__ == "__main__":
    main()
