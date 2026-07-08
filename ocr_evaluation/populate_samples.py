import os
import csv
import re
import textwrap
try:
    from PIL import Image, ImageDraw, ImageFont
except ImportError:
    Image = None

current_dir = os.path.dirname(os.path.abspath(__file__))
backend_dir = os.path.abspath(os.path.join(current_dir, ".."))
csv_path = os.path.join(backend_dir, "data", "dataset_scincare", "incidecoder_products.csv")
gt_dir = os.path.join(current_dir, "dataset", "ground_truth")
images_dir = os.path.join(current_dir, "dataset", "images_raw")

os.makedirs(gt_dir, exist_ok=True)
os.makedirs(images_dir, exist_ok=True)

if not os.path.exists(csv_path):
    print(f"Error: File CSV tidak ditemukan di {csv_path}")
    exit(1)

mapping_entries = []

with open(csv_path, "r", encoding="utf-8") as f:
    reader = csv.DictReader(f)
    # Kita ambil 15 produk pertama untuk dijadikan sampel evaluasi
    count = 2  # Mulai dari sample_002 karena sample_001 sudah ada
    for row in reader:
        if count > 16:  # Ambil 15 sampel (sample_002 sampai sample_016)
            break
            
        p_id = row.get("id")
        name = row.get("product_name")
        brand = row.get("brand")
        ingredients = row.get("ingredient_raw")
        
        if not name or not ingredients:
            continue
            
        sample_name = f"sample_{count:03d}"
        
        # 1. Tulis file teks utuh kemasan (Ground Truth)
        raw_text_content = f"INGREDIENTS: {ingredients}\n"
        with open(os.path.join(gt_dir, f"{sample_name}.txt"), "w", encoding="utf-8") as out_f:
            out_f.write(raw_text_content)
            
        # 2. Tulis file list ingredient (kunci jawaban pencocokan)
        with open(os.path.join(gt_dir, f"{sample_name}_ingredients.txt"), "w", encoding="utf-8") as out_f:
            out_f.write(ingredients + "\n")
            
        mapping_entries.append(f"{sample_name} -> {brand} - {name}")
        count += 1

# Tulis file pemetaan untuk referensi user
mapping_file_path = os.path.join(current_dir, "dataset", "mapping_list.txt")
with open(mapping_file_path, "w", encoding="utf-8") as map_f:
    map_f.write("=== DAFTAR PEMETAAN DATA SAMPEL EVALUASI OCR ===\n")
    map_f.write("\n".join(mapping_entries) + "\n")

print(f"Berhasil membuat {len(mapping_entries)} sampel Ground Truth (sample_002 s/d sample_{count-1:03d})")
print(f"File pemetaan ditulis di: {mapping_file_path}")

# Render gambar label sintetis untuk setiap sampel di Ground Truth yang belum memiliki gambar
def render_label_image(text, output_path):
    if Image is None:
        return
    lines = textwrap.wrap(text, width=65)
    line_height = 36
    padding = 50
    width = 1000
    height = padding * 2 + len(lines) * line_height
    
    img = Image.new("RGB", (width, height), color=(252, 252, 250))
    draw = ImageDraw.Draw(img)
    try:
        font = ImageFont.load_default(size=22)
    except TypeError:
        font = ImageFont.load_default()
        
    y = padding
    for line in lines:
        draw.text((padding, y), line, fill=(20, 20, 20), font=font)
        y += line_height
        
    img.save(output_path, "JPEG", quality=95)

print("\nMemeriksa ketersediaan gambar uji di dataset/images_raw/...")
img_count = 0
for file in sorted(os.listdir(gt_dir)):
    if file.endswith(".txt") and not file.endswith("_ingredients.txt"):
        sample_id = file[:-4]
        existing_imgs = [f for f in os.listdir(images_dir) if f.startswith(sample_id + ".")]
        if not existing_imgs:
            with open(os.path.join(gt_dir, file), "r", encoding="utf-8") as f:
                content = f.read().strip()
            out_jpg = os.path.join(images_dir, f"{sample_id}.jpg")
            render_label_image(content, out_jpg)
            img_count += 1
            print(f"  [+] Generated gambar label sintetis: {sample_id}.jpg")

print(f"Selesai! {img_count} gambar label baru dibuat. Total file gambar di images_raw: {len([f for f in os.listdir(images_dir) if f.lower().endswith(('.jpg','.jpeg','.png','.webp'))])}")
