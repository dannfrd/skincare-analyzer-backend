# Modul Penelitian & Evaluasi Akurasi OCR

Folder ini dibuat khusus untuk memfasilitasi penelitian Tugas Akhir (TA) Anda dalam membandingkan 4 mesin OCR (**Hybrid**, **Tesseract**, **MLKit**, dan **PaddleOCR**). 

Sistem ini membantu Anda mengukur akurasi pembacaan teks (**CER** & **WER**) serta akurasi pencocokan database bahan kosmetik (**Precision**, **Recall**, dan **F1-Score**) secara otomatis.

---

## 📂 Struktur Direktori

```text
ocr_evaluation/
├── README.md               <-- Petunjuk teknis penggunaan ini
├── evaluate.py             <-- Skrip Python utama pengukur metrik akurasi
├── dataset/
│   ├── ground_truth/       <-- Kunci jawaban (Teks asli yang 100% benar)
│   │   ├── [NamaSampel].txt               <-- Teks lengkap kemasan yang benar
│   │   └── [NamaSampel]_ingredients.txt   <-- Daftar ingredient benar (dipisah koma)
│   └── images_raw/         <-- File foto kemasan asli untuk dokumentasi Anda
└── results/
    ├── hybrid/             <-- Hasil pembacaan OCR Hybrid (dari Flutter)
    │   ├── [NamaSampel].txt               <-- Teks hasil scan
    │   └── [NamaSampel]_metadata.json     <-- [Opsional] Info waktu pemrosesan
    ├── tesseract/          <-- Hasil pembacaan OCR Tesseract murni
    ├── mlkit/              <-- Hasil pembacaan OCR MLKit murni
    ├── paddleocr/          <-- Hasil pembacaan OCR PaddleOCR Lokal (PP-OCRv4)
    ├── paddleocr_vl/       <-- Hasil pembacaan OCR PaddleOCR-VL-1.6 Cloud API (Vision-Language)
    └── summary_results.csv <-- REKAPITULASI HASIL (Otomatis dibuat oleh skrip)
```

---

## 🚀 Skrip Runner Otomatis untuk Pengujian Batch

Untuk menghemat waktu pengujian, Anda dapat menjalankan OCR batch secara otomatis terhadap semua foto kemasan di folder `dataset/images_raw/`:

### 1. Runner PaddleOCR-VL-1.6 Cloud API (Vision-Language - Paling Akurat)
Menggunakan model AI Studio API v2 (`PaddleOCR-VL-1.6`) untuk mengekstrak teks markdown, struktur tabel, dan daftar bahan dengan akurasi sangat tinggi:
```bash
python ocr_evaluation/run_paddleocr_vl_api.py
```
*(Opsional: tambahkan flag `--save_layout` untuk menyimpan dokumen markdown beserta potongan gambar deteksi tabel/potongan layout ke folder `results/paddleocr_vl/`)*.

### 2. Runner PaddleOCR Lokal (PP-OCRv4 dengan Spatial Line Clustering)
Menjalankan pemrosesan murni di perangkat CPU dengan algoritma pengelompokan baris spasial (*spatial line clustering*) agar urutan pembacaan tabel/kolom akurat:
```bash
python ocr_evaluation/run_paddleocr_local.py
```

### 3. Runner Tesseract Lokal
```bash
python ocr_evaluation/run_tesseract_local.py
```

---

## 🛠️ Langkah-Langkah Pengujian Penelitian

### Langkah 1: Siapkan Dataset Pengujian (Ground Truth)
Untuk setiap produk skincare yang Anda jadikan sampel (contoh nama sampel: `sample_001`):
1. Masukkan foto kemasan di folder `dataset/images_raw/` (untuk arsip penelitian Anda).
2. Tulis teks utuh yang tertulis di kemasan secara manual di dalam `dataset/ground_truth/sample_001.txt`.
3. Tulis daftar bahan aktif (ingredients) yang benar secara manual (dipisahkan tanda koma) di dalam `dataset/ground_truth/sample_001_ingredients.txt`.
   * *Contoh isi:* `WATER, GLYCERIN, NIACINAMIDE, PHENOXYETHANOL`

### Langkah 2: Kumpulkan Hasil Scan OCR dari Setiap Engine
Setiap kali Anda menembakkan gambar sampel ke mesin OCR:
1. **Untuk Hybrid:** Jalankan aplikasi Flutter Anda dalam mode debug, lakukan scan pada botol sampel, lalu salin teks hasil pembacaannya dan simpan ke `results/hybrid/sample_001.txt`.
2. **Untuk Engine Lain (Tesseract/MLKit/PaddleOCR):** Simpan output teks masing-masing di subfoldernya dengan nama file yang sama (`sample_001.txt`).
3. **[Opsional] Mencatat Waktu Eksekusi:** Jika ingin membandingkan kecepatan pemrosesan, buat file JSON pendukung dengan format `sample_001_metadata.json` di dalam folder hasil engine.
   * *Contoh isi:* `{"time_ms": 850}`

### Langkah 3: Jalankan Skrip Evaluasi
Buka terminal/command prompt di root folder backend (`skincare-analyzer-backend`), aktifkan virtual environment, dan jalankan perintah:

```bash
python ocr_evaluation/evaluate.py
```

Skrip akan otomatis:
* Mencari semua sampel di folder `ground_truth`.
* Menghitung **CER** & **WER** teks mentah untuk setiap engine.
* Menjalankan fungsi **Text Cleaning** backend untuk membersihkan teks dan mengekstrak bahan aktif.
* Menghitung **Exact Match** (pencocokan persis) dan **Fuzzy Match** (pencocokan toleran typo 80% seperti sistem produksi) antara hasil OCR dan Ground Truth.
* Menampilkan tabel ringkasan langsung di konsol dan mengekspor tabel detail lengkap ke file **`results/summary_results.csv`**.

---

## 📊 Penjelasan Metrik Akurasi Penelitian

1. **Character Error Rate (CER):** 
   Mengukur persentase kesalahan di tingkat huruf/karakter (salah baca, huruf hilang, atau huruf berlebih). Nilai **semakin mendekati 0% semakin baik**.
2. **Word Error Rate (WER):**
   Mengukur kesalahan tingkat kata. Berguna untuk mengukur kemudahan teks dibaca secara utuh. Nilai **semakin mendekati 0% semakin baik**.
3. **Exact Match (Ingredient):**
   Menguji akurasi ekstraksi jika teks dicocokkan secara persis (*case-insensitive*).
4. **Fuzzy Match (Ingredient):**
   Menguji akurasi ekstraksi dengan toleransi kemiripan kata di atas 80% (menggunakan algoritma pencari string terdekat). Ini sangat penting karena meskipun OCR memiliki banyak typo (CER tinggi), *fuzzy matching* sering kali dapat memperbaikinya dan mencocokkannya ke database bahan secara sempurna.
5. **Precision (Presisi):** 
   Dari daftar bahan yang dihasilkan OCR, berapa persen yang benar-benar ada di botol kemasan (menghindari deteksi bahan "palsu/halusinasi").
6. **Recall (Sensitivitas):**
   Dari daftar bahan yang ada di botol kemasan, berapa persen yang sukses dibaca oleh OCR (menghindari bahan terlewat, terutama bahan berbahaya/alergen).
7. **F1-Score:**
   Rata-rata harmonis penyeimbang antara Precision dan Recall.
