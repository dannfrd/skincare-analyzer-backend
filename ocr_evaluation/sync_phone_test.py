import os
import sys
import subprocess
import shutil

# Setup paths agar bisa memuat text cleaner
current_dir = os.path.dirname(os.path.abspath(__file__))
backend_dir = os.path.abspath(os.path.join(current_dir, ".."))
if backend_dir not in sys.path:
    sys.path.append(backend_dir)

try:
    from modules.text_cleaning import clean_and_tokenize
    has_cleaner = True
except ImportError:
    has_cleaner = False

def get_connected_device():
    try:
        res = subprocess.check_output(["adb", "devices"], universal_newlines=True)
        lines = [line.strip() for line in res.strip().split("\n")[1:] if line.strip() and "device" in line]
        if not lines:
            return None
        return lines[0].split("\t")[0]
    except Exception:
        return None

def pull_from_camera(device_id, dest_dir, count=15):
    print(f"[INFO] Menghubungkan ke perangkat HP ({device_id})...")
    
    # Cari foto JPG/JPEG terbaru di folder kamera HP
    cmd_list = ["adb", "-s", device_id, "shell", "ls -t /sdcard/DCIM/Camera/*.jpg /sdcard/DCIM/Camera/*.jpeg 2>/dev/null"]
    try:
        res = subprocess.check_output(cmd_list, universal_newlines=True)
        remote_files = [f.strip() for f in res.strip().split("\n") if f.strip()][:count]
    except Exception as e:
        print(f"[ERROR] Gagal membaca daftar foto di HP: {e}")
        return []
        
    if not remote_files:
        print("[WARNING] Tidak ada foto ditemukan di /sdcard/DCIM/Camera/")
        return []
        
    print(f"[INFO] Menemukan {len(remote_files)} foto terbaru di kamera HP. Menarik ke laptop...")
    os.makedirs(dest_dir, exist_ok=True)
    
    pulled_files = []
    for i, r_file in enumerate(remote_files, start=1):
        ext = os.path.splitext(r_file)[1].lower()
        if not ext:
            ext = ".jpg"
        local_name = f"sample_{i:03d}{ext}"
        local_path = os.path.join(dest_dir, local_name)
        
        print(f"  [{i}/{len(remote_files)}] Menarik {os.path.basename(r_file)} -> {local_name}...")
        cmd_pull = ["adb", "-s", device_id, "pull", r_file, local_path]
        subprocess.run(cmd_pull, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        
        if os.path.exists(local_path):
            pulled_files.append(local_path)
            
    return pulled_files

def create_ground_truth_for_single_product(gt_dir, count, gt_text):
    print(f"\n[INFO] Membuat {count} file Ground Truth untuk pengujian produk tunggal...")
    os.makedirs(gt_dir, exist_ok=True)
    
    # Format ingredients text
    if has_cleaner:
        tokens = clean_and_tokenize(gt_text)
        ing_content = "\n".join(tokens)
    else:
        ing_content = "\n".join([x.strip() for x in gt_text.replace("INGREDIENTS:", "").split(",") if x.strip()])
        
    for i in range(1, count + 1):
        txt_path = os.path.join(gt_dir, f"sample_{i:03d}.txt")
        ing_path = os.path.join(gt_dir, f"sample_{i:03d}_ingredients.txt")
        
        with open(txt_path, "w", encoding="utf-8") as f:
            f.write(gt_text if "INGREDIENTS:" in gt_text.upper() else f"INGREDIENTS: {gt_text}")
            
        with open(ing_path, "w", encoding="utf-8") as f:
            f.write(ing_content)
            
    print(f"[SUKSES] {count} file Ground Truth berhasil disiapkan di {gt_dir}")

def main():
    print("==================================================")
    print("      SINKRONISASI FOTO HP VIA ADB & SETUP TA     ")
    print("==================================================")
    
    device_id = get_connected_device()
    if not device_id:
        print("[ERROR] Tidak ada HP Android yang terhubung via ADB.")
        print("Pastikan USB Debugging aktif di HP Anda dan kabel terhubung dengan baik.")
        return
        
    print(f"[SUCCESS] HP Terdeteksi: {device_id}")
    
    # Konfigurasi Skenario 1 (Single Product 15 kali)
    skenario_dir = os.path.join(current_dir, "dataset", "skenario_1_single_product")
    
    # Contoh teks komposisi default jika tidak diberikan via argumen
    default_gt = "INGREDIENTS: WATER, GLYCERIN, NIACINAMIDE, BUTYLENE GLYCOL, SALICYLIC ACID, SODIUM HYALURONATE, PHENOXYETHANOL, ALLANTOIN, CENTELLA ASIATICA EXTRACT, CARBOMER."
    
    gt_text = default_gt
    count = 15
    product_name = "Single Product Test"
    
    for i, arg in enumerate(sys.argv):
        if arg == "--gt_text" and i + 1 < len(sys.argv):
            gt_text = sys.argv[i + 1]
        elif arg == "--count" and i + 1 < len(sys.argv):
            count = int(sys.argv[i + 1])
        elif arg == "--product_name" and i + 1 < len(sys.argv):
            product_name = sys.argv[i + 1]
            
    print(f"\n[STEP 1] Menarik {count} foto terbaru dari kamera HP ke laptop...")
    pulled = pull_from_camera(device_id, skenario_dir, count=count)
    
    if not pulled:
        print("[ERROR] Gagal menarik foto. Silakan ambil foto produk di HP terlebih dahulu.")
        return
        
    print(f"\n[STEP 2] Menyiapkan Ground Truth untuk {len(pulled)} foto pengujian...")
    create_ground_truth_for_single_product(skenario_dir, len(pulled), gt_text)
    
    print("\n==================================================")
    print("Sinkronisasi Selesai! Siap untuk pengujian murni PaddleOCR:")
    print(f"1. python ocr_evaluation/run_paddleocr_local.py --dataset_dir {skenario_dir}")
    print(f'2. python ocr_evaluation/evaluate.py --engine paddleocr --gt_dir {skenario_dir} --product_name "{product_name}"')
    print("==================================================")

if __name__ == "__main__":
    main()
