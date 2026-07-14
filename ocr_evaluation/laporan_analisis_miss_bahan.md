# Laporan Analisis Miss Bahan & Error OCR (False Negatives & False Positives)

Dokumen ini merupakan laporan **analisis mendalam** terhadap bahan-bahan kosmetik yang berhasil dikenali (*True Positives*), terlewat/gagal terbaca (*False Negatives / Missed Ingredients*), dan token yang salah terdeteksi (*False Positives / OCR Noise*) oleh sistem evaluasi OCR berbasis PaddleOCR.

Skrip pembuatan laporan ini: `ocr_evaluation/error_analysis.py`

---

## SKENARIO 1: Single Product / Multi Trial (Pengujian Konsistensi 1 Produk)

### Deskripsi Skenario 1
- **Produk Uji:** G2G Cleanser (Pembersih Wajah Botol Biru)
- **Total Bahan Asli (Ground Truth):** 16 bahan INCI
- **Jumlah Trial / Pengujian:** 11 kali pengambilan gambar berbeda
- **Engine OCR:** PaddleOCR
- **Tujuan:** Mengukur konsistensi dan keandalan sistem OCR pada satu produk yang sama dengan kondisi pengambilan gambar yang bervariasi (sudut, cahaya, jarak).

---

### Tabel Ringkasan Skenario 1

| No. | Kode Trial | Berhasil | Total GT | Miss | FP (Noise) | Akurasi Match |
|:---:|:-----------|:--------:|:--------:|:----:|:----------:|:-------------:|
| 1 | `trial_01` | 16 | 16 | 0 | 1 | **100%** |
| 2 | `trial_02` | 16 | 16 | 0 | 1 | **100%** |
| 3 | `trial_03` | 15 | 16 | 1 | 1 | **93.75%** |
| 4 | `trial_04` | 12 | 16 | 4 | 0 | **75.00%** |
| 5 | `trial_05` | 15 | 16 | 1 | 1 | **93.75%** |
| 6 | `trial_06` | 16 | 16 | 0 | 1 | **100%** |
| 7 | `trial_07` | 14 | 16 | 2 | 1 | **87.50%** |
| 8 | `trial_08` | 16 | 16 | 0 | 1 | **100%** |
| 9 | `trial_09` | 15 | 16 | 1 | 1 | **93.75%** |
| 10 | `trial_10` | 15 | 16 | 1 | 1 | **93.75%** |
| 11 | `trial_11` | 12 | 16 | 4 | 1 | **75.00%** |

> **Rata-rata Akurasi Match Skenario 1:** ~91.5% (dari 11 trial pengujian)

---

### Analisis Detail Per Trial — Skenario 1

#### Trial 01 — g2g_cleanser_trial_01
| Kategori | Detail |
|:---------|:-------|
| Berhasil Dikenali | 16 / 16 bahan (100%) |
| Bahan MISS | *(Tidak ada)* |
| Token Noise (FP) | `BLUEBERRY REFERS TOVACCINIUM MYRTILLUS FRUIT EXTRACT` |
| Keterangan | Scan sempurna. Noise FP berasal dari keterangan pemasaran ("BLUEBERRY refers to...") yang tidak dipisah tanda koma oleh kemasan, sehingga terbaca oleh OCR sebagai satu token panjang. |

---

#### Trial 02 — g2g_cleanser_trial_02
| Kategori | Detail |
|:---------|:-------|
| Berhasil Dikenali | 16 / 16 bahan (100%) |
| Bahan MISS | *(Tidak ada)* |
| Token Noise (FP) | `BLUEBERRY REFERS TOVACCINIUM MYRTILLUS FRUITE EXTRACT` |
| Keterangan | Sama seperti Trial 01. Penambahan huruf `E` pada `FRUITE` menunjukkan minor typo pada scan kedua, namun tidak memengaruhi pencocokan bahan utama. |

---

#### Trial 03 — g2g_cleanser_trial_03
| Kategori | Detail |
|:---------|:-------|
| Berhasil Dikenali | 15 / 16 bahan (93.75%) |
| Bahan MISS | `SORBITOL` |
| Detail Penyebab | **OCR Typo / Salah Karakter:** `SORBITOL` terbaca menjadi token gabungan `SORBITOL DISODIUM EDTA` karena koma/pemisah antara kedua bahan tersebut tidak terdeteksi OCR, sehingga fuzzy match mengembalikan kemiripan di bawah ambang batas 0.72. |
| Token Noise (FP) | `BLUEBERRY REFERS TOVACCINIUM MYRTILLUS FRUIT EXTRACT` |

---

#### Trial 04 — g2g_cleanser_trial_04
| Kategori | Detail |
|:---------|:-------|
| Berhasil Dikenali | 12 / 16 bahan (75.00%) |
| Bahan MISS (4 bahan) | `PROPYLENE GLYCOL`, `SORBITOL`, `BHT`, `AROMA` |
| Detail Penyebab MISS | |
| — `PROPYLENE GLYCOL` | **OCR Typo:** Terbaca sebagai `BUTYLENE GLYCOL BHT` (dua bahan tergabung tanpa koma). |
| — `SORBITOL` | **OCR Typo:** Terbaca sebagai `SORBITOLDISODIUM EDTA` (tidak ada spasi/koma pemisah). |
| — `BHT` | **Gagal terdeteksi:** Bahan terlalu pendek (3 huruf), kemungkinan terlewat oleh OCR atau tergabung dengan bahan sebelumnya. |
| — `AROMA` | **Cut-off Bawah:** Berada di urutan bawah daftar komposisi, terpotong oleh batas frame kamera pengambil gambar. |
| Token Noise (FP) | *(Tidak ada)* |

---

#### Trial 05 — g2g_cleanser_trial_05
| Kategori | Detail |
|:---------|:-------|
| Berhasil Dikenali | 15 / 16 bahan (93.75%) |
| Bahan MISS | `BHT` |
| Detail Penyebab | **Gagal terdeteksi:** Singkatan `BHT` hanya 3 karakter, mudah terpotong atau tidak dikenali oleh OCR sebagai token tersendiri. |
| Token Noise (FP) | `BLUEBERRY REFERS TOVACCINIUM MYRTILLUS FRUIT EXTRACT` |

---

#### Trial 06 — g2g_cleanser_trial_06
| Kategori | Detail |
|:---------|:-------|
| Berhasil Dikenali | 16 / 16 bahan (100%) |
| Bahan MISS | *(Tidak ada)* |
| Token Noise (FP) | `BLUEBERRY REFERS TOVACCINIUM MYRTILLUS FRUIT EXTRACT` |
| Keterangan | Scan sempurna. Noise FP muncul kembali dari teks pemasaran kemasan, konsisten di hampir seluruh trial. |

---

#### Trial 07 — g2g_cleanser_trial_07
| Kategori | Detail |
|:---------|:-------|
| Berhasil Dikenali | 14 / 16 bahan (87.50%) |
| Bahan MISS (2 bahan) | `DISODIUM EDTA`, `BUTYLENE GLYCOL` |
| Detail Penyebab MISS | |
| — `DISODIUM EDTA` | **OCR Typo:** Terbaca sebagai `SODIUM HYDROXIDE` (karakter `DI-` di awal kata hilang, sisa teks mirip bahan lain). |
| — `BUTYLENE GLYCOL` | **OCR Typo:** Terbaca sebagai `PROPYLENE GLYCOL` (kata `BUTYLENE` vs `PROPYLENE` sangat mirip secara visual pada kemasan kecil). |
| Token Noise (FP) | `EXTRACT` (token sisa potongan kata yang tidak bermakna sendiri) |

---

#### Trial 08 — g2g_cleanser_trial_08
| Kategori | Detail |
|:---------|:-------|
| Berhasil Dikenali | 16 / 16 bahan (100%) |
| Bahan MISS | *(Tidak ada)* |
| Token Noise (FP) | `BLUEBERRYREFERS TOVACCINIUM MYRTILLUS FRUIT EXTRACT` |
| Keterangan | Scan sempurna. Spasi hilang antara `BLUEBERRY` dan `REFERS` pada trial ini dibanding trial lain, namun tidak memengaruhi pencocokan bahan utama. |

---

#### Trial 09 — g2g_cleanser_trial_09
| Kategori | Detail |
|:---------|:-------|
| Berhasil Dikenali | 15 / 16 bahan (93.75%) |
| Bahan MISS | `SORBITOL` |
| Detail Penyebab | **OCR Typo:** Terbaca sebagai `SORBITOLDISODIUM EDTA` (tidak ada spasi pemisah). Pola kesalahan yang sama dengan Trial 03. |
| Token Noise (FP) | `BLUEBERRY REFERS TOVACCINIUM MYRTILLUS FRUIT EXTRACT` |

---

#### Trial 10 — g2g_cleanser_trial_10
| Kategori | Detail |
|:---------|:-------|
| Berhasil Dikenali | 15 / 16 bahan (93.75%) |
| Bahan MISS | `BUTYLENE GLYCOL` |
| Detail Penyebab | **OCR Typo:** Terbaca sebagai `PROPYLENE GLYCOL`. Kata `BUTYLENE` dan `PROPYLENE` memiliki bentuk karakter yang sangat mirip secara visual (B-P, U-R, E-E). |
| Token Noise (FP) | `BLUEBERRY REFERS TOVACCINIUM MYRTILLUS FRUIT EXTRACT` |

---

#### Trial 11 — g2g_cleanser_trial_11
| Kategori | Detail |
|:---------|:-------|
| Berhasil Dikenali | 12 / 16 bahan (75.00%) |
| Bahan MISS (4 bahan) | `BUTYLENE GLYCOL`, `BHT`, `CHLORPHENESIN`, `POLYAMINOPROPYL BIGUANIDE` |
| Detail Penyebab MISS | |
| — `BUTYLENE GLYCOL` | **OCR Typo:** Terbaca sebagai `PROPYLENE GLYCOL`. |
| — `BHT` | **Gagal terdeteksi:** Token 3 karakter, tidak cukup panjang untuk dicocokkan. |
| — `CHLORPHENESIN` | **Cut-off Bawah:** Bahan di bagian bawah komposisi, terpotong oleh batas frame kamera. |
| — `POLYAMINOPROPYL BIGUANIDE` | **OCR Typo Parah:** Terbaca sebagai satu token panjang gabungan semua bahan akhir: `DISODIUM EDTABUTYLENE GLYCOLBHTCHLORPHENESINPOLYAMINOPROPYL BIGUANIDE` (5 bahan sekaligus tersatu tanpa koma). |
| Token Noise (FP) | `EXTRACT` (sisa potongan kata yang tidak bermakna sendiri) |

---

### Temuan Kunci Skenario 1

| Penyebab Miss | Jumlah Kejadian | Bahan Terdampak |
|:---|:---:|:---|
| OCR Typo / Substitusi Karakter | 8 | `BUTYLENE GLYCOL` (3x), `SORBITOL` (3x), `DISODIUM EDTA`, `POLYAMINOPROPYL BIGUANIDE` |
| Gagal Terdeteksi (Token Pendek) | 3 | `BHT` (3x di Trial 04, 05, 11) |
| Terpotong Bawah (Cut-off) | 3 | `AROMA`, `CHLORPHENESIN`, serta `BHT` (bersamaan di Trial 11) |

> **Insight:** Bahan `BUTYLENE GLYCOL`, `SORBITOL`, dan `BHT` adalah bahan yang paling konsisten *miss* di Skenario 1. Hal ini mengindikasikan bahwa bahan-bahan ini memiliki karakteristik visual pada kemasan yang membuatnya rentan terhadap OCR error, bukan kelemahan sistemik engine OCR secara keseluruhan.

---
---

## SKENARIO 2: Multiple Products / Multi Brand (Pengujian Generalisasi 9 Produk)

### Deskripsi Skenario 2
- **Jumlah Produk Uji:** 9 produk dari berbagai merek
- **Engine OCR:** PaddleOCR
- **Tujuan:** Mengukur kemampuan generalisasi sistem dalam mengenali bahan kosmetik dari beragam jenis kemasan, jenis teks, ukuran font, dan kondisi pencetakan yang berbeda-beda.

---

### Tabel Ringkasan Skenario 2

| No. | Kode Sample | Nama Produk | Berhasil | Total GT | Miss | FP | Akurasi |
|:---:|:-----------|:------------|:--------:|:--------:|:----:|:--:|:-------:|
| 1 | `g2g_cleanser` | G2G Cleanser | 16 | 16 | 0 | 1 | **100%** |
| 2 | `exfoliasi_skintific` | Exfoliasi Skintific | 30 | 31 | 1 | 0 | **96.77%** |
| 3 | `masker_camille` | Masker Camille | 22 | 24 | 2 | 0 | **91.67%** |
| 4 | `lipcare_madame_gie` | Lipcare Madame Gie | 10 | 13 | 3 | 0 | **76.92%** |
| 5 | `sunscreen_emina` | Sunscreen Emina | 41 | 46 | 5 | 0 | **89.13%** |
| 6 | `masker_komedo` | Masker Hidung Komedo | 7 | 14 | 7 | 1 | **50.00%** |
| 7 | `cleanser_panthenol` | Facial Wash Scora | 12 | 32 | 20 | 1 | **37.50%** |
| 8 | `facial_wash_g2g` | Facial Wash G2G | 17 | 36 | 19 | 0 | **47.22%** |
| 9 | `facial_wash_kahf` | Facial Wash Kahf | 21 | 46 | 25 | 0 | **45.65%** |
| 10 | `wardah_face_mist` | Wardah Face Mist | 4 | 16 | 12 | 1 | **25.00%** |

> **Rata-rata Akurasi Match Skenario 2:** ~65.9% (dari 10 produk berbeda)

---

### Analisis Detail Per Produk — Skenario 2

#### Produk 1 — G2G Cleanser (`g2g_cleanser`)
| Kategori | Detail |
|:---------|:-------|
| Berhasil Dikenali | **16 / 16 bahan (100%)** |
| Bahan MISS | *(Tidak ada — sempurna)* |
| Token Noise (FP) | `BLUEBERRYREFERS TOVACCINIUM MYRTILLUS FRUIT EXTRACT` |
| Keterangan | Kemasan bersih dengan font cetak yang jelas dan kontras tinggi. Satu-satunya "kesalahan" adalah noise dari kalimat pemasaran produk yang tidak terpisahkan oleh koma dari daftar INCI, bukan error OCR bahan itu sendiri. |

---

#### Produk 2 — Exfoliasi Skintific (`exfoliasi_skintific`)
| Kategori | Detail |
|:---------|:-------|
| Berhasil Dikenali | **30 / 31 bahan (96.77%)** |
| Bahan MISS (1 bahan) | `1` |
| Detail Penyebab | **Gagal terdeteksi:** Angka `1` yang merupakan bagian pertama dari bahan `1,2-HEXANEDIOL` terpisah menjadi token mandiri ketika koma antara `1` dan `2-HEXANEDIOL` terbaca sebagai pemisah daftar, bukan sebagai tanda penghubung nama INCI. Token tunggal `1` kemudian gagal dicocokkan karena terlalu pendek dan tidak bermakna secara INCI. |
| Token Noise (FP) | *(Tidak ada)* |

---

#### Produk 3 — Masker Camille (`masker_camille`)
| Kategori | Detail |
|:---------|:-------|
| Berhasil Dikenali | **22 / 24 bahan (91.67%)** |
| Bahan MISS (2 bahan) | `POTASSIUM SORBATE`, `1` |
| Detail Penyebab MISS | |
| — `POTASSIUM SORBATE` | **OCR Typo:** Terbaca sebagai `SODIUM BENZOATE`. Kedua bahan merupakan pengawet yang namanya memiliki pola serupa (`___IUM ___ATE`), sehingga OCR salah mengenali kombinasi hurufnya. Fuzzy match gagal karena similaritas POTASSIUM vs SODIUM terlalu rendah. |
| — `1` | **Cut-off Bawah:** Angka `1` dari bahan `1,2-HEXANEDIOL` berada di ujung bawah daftar komposisi dan terpotong oleh batas frame saat pengambilan gambar. |
| Token Noise (FP) | *(Tidak ada)* |

---

#### Produk 4 — Lipcare Madame Gie (`lipcare_madame_gie`)
| Kategori | Detail |
|:---------|:-------|
| Berhasil Dikenali | **10 / 13 bahan (76.92%)** |
| Bahan MISS (3 bahan) | `CITRULLUS LANATUS (WATERMELON) SEED OIL`, `AROMA`, `PENTAERYTHRITYL TETRA-DI-T-BUTYL HYDROXYHYDROCINNAMATE` |
| Detail Penyebab MISS | |
| — `CITRULLUS LANATUS (WATERMELON) SEED OIL` | **Gagal terdeteksi:** Bahan tersebut tidak ditemukan oleh OCR karena kemasan lip care menggunakan format teks dua baris tanpa koma pemisah, sehingga nama bahan ini bergabung dengan bahan setelahnya menjadi satu blok token. |
| — `AROMA` | **Cut-off Bawah:** Berada di ujung bawah daftar INCI, terpotong oleh batas frame pengambilan gambar. |
| — `PENTAERYTHRITYL TETRA-DI-T-BUTYL HYDROXYHYDROCINNAMATE` | **OCR Typo + Merged Token:** OCR membaca bahan terakhir ini beserta 3 bahan sebelumnya (`BUTYROSPERMUM PARKII (SHEA) BUTTER`, `CITRULLUS LANATUS...`, `AROMA`) sebagai satu kalimat panjang tanpa pemisah: `BUTYROSPERMUM PARKII (SHEA) BUTTER CITRULLUS LANATUS (WATERMELON SEED OIL AROMA PENTAERYTHRITYL TETRA-DI-T-BUTYL HYDROXYHYDROCINNAMATE`. Fuzzy match tidak bisa mengisolasi nama bahan individu dari token raksasa ini. |
| Token Noise (FP) | *(Tidak ada)* |

---

#### Produk 5 — Sunscreen Emina (`sunscreen_emina`)
| Kategori | Detail |
|:---------|:-------|
| Berhasil Dikenali | **41 / 46 bahan (89.13%)** |
| Bahan MISS (5 bahan) | `CETEARYL OLIVATE`, `DIPROPYLENE GLYCOL`, `SODIUM HYDROXIDE`, `SODIUM SULFITE`, `ACETYL TYROSINE` |
| Detail Penyebab MISS | |
| — `CETEARYL OLIVATE` | **OCR Typo:** Terbaca sebagai `SORBITAN OLIVATE`. Kata `CETEARYL` dan `SORBITAN` memiliki panjang yang berbeda namun sama-sama sering muncul berpasangan dengan `OLIVATE` pada pelembab, sehingga OCR cenderung mengonfirmasi konteks tersebut. |
| — `DIPROPYLENE GLYCOL` | **OCR Typo:** Terbaca sebagai `PROPYLENE GLYCOL` (prefiks `DI-` tidak terdeteksi, kemungkinan karena ukuran font kecil pada kemasan tube sunscreen yang menyempit). |
| — `SODIUM HYDROXIDE` | **OCR Typo (Token Gabungan):** Terbaca sebagai `DISODIUM EDTA SODIUM HYDROXIDE` (dua bahan tergabung tanpa pemisah, sehingga similaritas turun di bawah 0.72 untuk bahan `SODIUM HYDROXIDE` sendiri). |
| — `SODIUM SULFITE` | **OCR Typo (Token Gabungan):** Terbaca sebagai `CITRIC ACID SODIUM SULFITE` (sama, dua bahan tergabung). |
| — `ACETYL TYROSINE` | **OCR Typo:** Terbaca sebagai `AMINOMETHYL PROPANOL`. Nama bahan berbeda namun memiliki pola visual serupa di kemasan sunscreen latar putih berkilap. |
| Token Noise (FP) | *(Tidak ada)* |

---

#### Produk 6 — Masker Hidung Komedo (`masker_komedo`)
| Kategori | Detail |
|:---------|:-------|
| Berhasil Dikenali | **7 / 14 bahan (50.00%)** |
| Bahan MISS (7 bahan) | `GLYCERIN`, `BUTYLENE GLYCOL`, `POLYVINYL ALCOHOL`, `CHARCOAL POWDER`, `GINKGO BILOBA LEAF EXTRACT`, `BAMBUSA VULGARIS (BAMBOO) EXTRACT`, `FRAGRANCE (PARFUM)` |
| Detail Penyebab MISS | |
| — `GLYCERIN` | **Cut-off Atas:** Bahan berada di posisi atas daftar (urutan ke-2/3), terpotong karena area scan dimulai terlambat (bagian atas label tidak masuk frame). |
| — `BUTYLENE GLYCOL` | **Cut-off Atas:** Sama, berada di posisi awal daftar komposisi yang terpotong. |
| — `POLYVINYL ALCOHOL` | **Gagal terdeteksi:** Kemungkinan teks tersamar oleh latar gelap patch masker hidung sehingga kontras tidak cukup untuk OCR. |
| — `CHARCOAL POWDER` | **Gagal terdeteksi:** Kata `CHARCOAL` berwarna gelap pada latar gelap produk, menyebabkan kontras optical sangat rendah. |
| — `GINKGO BILOBA LEAF EXTRACT` | **OCR Typo Parah:** Terbaca sebagai `CAMELLIA SINENSIS (GREEN TEA) GINKGO BLOBA LEAF EXTRACT` (penambahan nama bahan lain di depannya dan typo `BLOBA` vs `BILOBA`). Fuzzy match gagal mengisolasi bahan asli. |
| — `BAMBUSA VULGARIS (BAMBOO) EXTRACT` | **OCR Typo Parah:** Terbaca hanya sebagai `AQUA EXTRACT` (nama genus tanaman terabaikan sepenuhnya, mungkin tercetak sangat kecil atau berdampingan dengan bahan lain). |
| — `FRAGRANCE (PARFUM)` | **OCR Typo (Token Gabungan):** Terbaca sebagai `FRAGRANCE SODIUM HYALURONATE` (kata `PARFUM` dalam tanda kurung hilang dan nama bahan berbeda muncul bergabung). |
| Token Noise (FP) | `LEAT EXTRACT` (typo dari `LEAF EXTRACT`, sisa token yang tidak bermakna) |

---

#### Produk 7 — Facial Wash Scora / Cleanser Panthenol (`cleanser_panthenol`)
| Kategori | Detail |
|:---------|:-------|
| Berhasil Dikenali | **12 / 32 bahan (37.50%)** |
| Bahan MISS (20 bahan) | `COCAMIDOPROPYL BETAINE`, `GLYCERIN`, `ACRYLATES COPOLYMER`, `SODIUM METHYL COCOYL TAURATE`, `POTASSIUM COCOYL GLYCINATE`, `SODIUM BENZOATE`, `ALLANTOIN`, `CITRIC ACID`, `DISODIUM EDTA`, `ETHYLHEXYLGLYCERIN`, `MICROCRYSTALLINE CELLULOSE`, `SUCROSE`, `ZEA MAYS STARCH`, `TITANIUM DIOXIDE`, `PENTYLENE GLYCOL`, `BIFIDA FERMENT LYSATE`, `LACTOBACILLUS FERMENT LYSATE`, `1`, `2-HEXANEDIOL`, `HYDROLYZED SODIUM HYALURONATE` |
| Detail Penyebab MISS | |
| — `COCAMIDOPROPYL BETAINE` | **Cut-off Atas:** Bahan di urutan awal, terpotong karena label melengkung (botol silinder). |
| — `GLYCERIN` | **Cut-off Atas:** Sama, terletak di awal daftar. |
| — `ACRYLATES COPOLYMER` | **OCR Typo:** Terbaca sebagai `SODIUM HYALURONATE CROSSPOLYMER`. |
| — `SODIUM METHYL COCOYL TAURATE` | **OCR Typo:** Terbaca sebagai `SODIUM HYALURONATE` (kata nama produk lain mendominasi karena kemasan melengkung). |
| — `POTASSIUM COCOYL GLYCINATE` | **OCR Typo:** Terbaca sebagai `CITRIC ACID POTASSIUM COCOATE` (nama bahan terpecah/bergabung). |
| — `SODIUM BENZOATE` | **OCR Typo:** Terbaca sebagai `SODIUM HYALURONATE`. |
| — `ALLANTOIN` | **OCR Typo:** Terbaca sebagai `MANNITOL` (kata yang panjangnya mirip dan sering muncul berdekatan pada formulasi serupa). |
| — `CITRIC ACID` | **OCR Typo:** Terbaca sebagai `TRANEXAMIC ACID`. |
| — `DISODIUM EDTA` | **OCR Typo (Token Gabungan):** Terbaca sebagai `PHENOXYETHANOL DISODIUM EDTA`. |
| — `ETHYLHEXYLGLYCERIN` | **Gagal terdeteksi sepenuhnya.** |
| — `MICROCRYSTALLINE CELLULOSE` | **Gagal terdeteksi sepenuhnya.** |
| — `SUCROSE` | **Gagal terdeteksi sepenuhnya.** |
| — `ZEA MAYS STARCH` | **Gagal terdeteksi sepenuhnya.** |
| — `TITANIUM DIOXIDE` | **Gagal terdeteksi sepenuhnya.** |
| — `PENTYLENE GLYCOL` | **Gagal terdeteksi sepenuhnya.** |
| — `BIFIDA FERMENT LYSATE` | **OCR Typo:** Terbaca sebagai `LACTOCOCCUS FERMENT LYSATE` (genus bakteri salah dibaca, kemungkinan karena resolusi rendah pada nama INCI yang panjang). |
| — `LACTOBACILLUS FERMENT LYSATE` | **OCR Typo:** Sama, terbaca sebagai `LACTOCOCCUS FERMENT LYSATE`. |
| — `1` | **Cut-off Bawah:** Angka dari `1,2-HEXANEDIOL` terpotong. |
| — `2-HEXANEDIOL` | **OCR Typo:** Terbaca sebagai `MANNITOL`. |
| — `HYDROLYZED SODIUM HYALURONATE` | **OCR Typo:** Terbaca sebagai `SODIUM HYALURONATE` (kata `HYDROLYZED` di awal terlewat oleh OCR). |
| Token Noise (FP) | `HYDROLYZED SOONNNNNNNE ONNARE` (artefak OCR berat akibat pantulan cahaya/glare pada kemasan transparan) |

---

#### Produk 8 — Facial Wash G2G Pink (`facial_wash_g2g`)
| Kategori | Detail |
|:---------|:-------|
| Berhasil Dikenali | **17 / 36 bahan (47.22%)** |
| Bahan MISS (19 bahan) | `AQUA`, `GLYCERIN`, `MYRISTIC ACID`, `POTASSIUM HYDROXIDE`, `STEARIC ACID`, `HYDROXYPROPYL METHYLCELLULOSE`, `MENTHOL`, `1`, `2-HEXANEDIOL`, `BUTYLENE GLYCOL`, `FOMES OFFICINALIS EXTRACT`, `PEG-40 HYDROGENATED CASTOR OIL`, `HYDROXYACETOPHENONE`, `AROMA`, `METHYLPARABEN`, `PHENOXYETHANOL`, `SODIUM BENZOATE`, `CI 77499`, `BHA` |
| Detail Penyebab MISS | |
| — `AQUA` | **Cut-off Atas:** Bahan pertama dalam daftar INCI (urutan paling atas), terpotong oleh batas atas frame scan. |
| — `GLYCERIN` | **OCR Typo:** Terbaca sebagai `GLYCERYL STEARATE`. |
| — `MYRISTIC ACID` | **OCR Typo:** Terbaca sebagai `PALMITIC ACID` (keduanya adalah asam lemak C14 vs C16 dengan nama serupa). |
| — `POTASSIUM HYDROXIDE` | **OCR Typo:** Terbaca sebagai `SODIUM CHLORIDE`. |
| — `STEARIC ACID` | **OCR Typo:** Terbaca sebagai `LAURIC ACID`. |
| — `HYDROXYPROPYL METHYLCELLULOSE` | **OCR Typo Parah (Merged Token):** Terbaca sebagai satu blok raksasa `DISODIUM EDTAHYDROXYPROPYLMETHYLCELLULOSE BHAREFERS TO SALICYLICACID` (beberapa bahan dan catatan kemasan tergabung tanpa pemisah). |
| — `MENTHOL` | **Gagal terdeteksi sepenuhnya.** |
| — `1`, `2-HEXANEDIOL` | **Gagal terdeteksi:** Koma dalam nama INCI `1,2-HEXANEDIOL` diinterpretasi sebagai pemisah daftar. |
| — `BUTYLENE GLYCOL` | **OCR Typo:** Terbaca sebagai `LAURYL GLUCOSIDE`. |
| — `FOMES OFFICINALIS EXTRACT` | **OCR Typo:** Terbaca sebagai `CENTELLA ASIATICA LEAF EXTRACT` (nama genus/spesies jamur yang sama sekali berbeda dengan tanaman centella). |
| — `PEG-40 HYDROGENATED CASTOR OIL` | **Gagal terdeteksi sepenuhnya.** |
| — `HYDROXYACETOPHENONE`, `AROMA`, `PHENOXYETHANOL`, `CI 77499`, `BHA` | **Cut-off Bawah:** Bahan-bahan di urutan akhir daftar komposisi, terpotong oleh batas bawah frame scan. |
| — `METHYLPARABEN` | **OCR Typo:** Terbaca sebagai `PROPYLPARABEN` (perbedaan hanya di prefiks `METHYL-` vs `PROPYL-`). |
| — `SODIUM BENZOATE` | **OCR Typo:** Terbaca sebagai `SODIUM CHLORIDE`. |
| Token Noise (FP) | *(Tidak ada)* |

---

#### Produk 9 — Facial Wash Kahf (`facial_wash_kahf`)
| Kategori | Detail |
|:---------|:-------|
| Berhasil Dikenali | **21 / 46 bahan (45.65%)** |
| Bahan MISS (25 bahan) | `SACCHARIDE ISOMERATE`, `KAOLIN`, `SALICYLIC ACID`, `FRAGRANCE`, `MENTHOL`, `ALLANTOIN`, `HYDROXYPROPYL METHYLCELLULOSE`, `ETHYLHEXYLGLYCERIN`, `MENTHYL LACTATE`, `PEG-40 HYDROGENATED CASTOR OIL`, `PPG-26-BUTETH-26`, `SALVIA OFFICINALIS (SAGE) LEAF EXTRACT`, `CITRIC ACID`, `SODIUM CITRATE`, `SODIUM BENZOATE`, `TRIDECETH-9`, `LAURETH-21`, `1`, `2-HEXANEDIOL`, `AMINOMETHYL PROPANEDIOL`, `SODIUM DEHYDROACETATE`, `CI 77891`, `CI 19140`, `CI 77266`, `CI 42090` |
| Detail Penyebab MISS | |
| — `SACCHARIDE ISOMERATE` | **OCR Typo:** Terbaca sebagai `POTASSIUM SORBATE`. |
| — `KAOLIN` | **Gagal terdeteksi:** Kata pendek, kemungkinan tergabung dengan bahan sebelumnya. |
| — `SALICYLIC ACID` | **OCR Typo:** Terbaca sebagai `STEARIC ACID`. |
| — `FRAGRANCE`, `ALLANTOIN`, `HYDROXYPROPYL METHYLCELLULOSE`, `PPG-26-BUTETH-26`, `SALVIA OFFICINALIS LEAF EXTRACT`, `TRIDECETH-9`, `LAURETH-21`, `1` | **Gagal terdeteksi sepenuhnya:** Bahan-bahan ini kemungkinan tertutup pantulan cahaya (glare) pada botol pump hitam mengkilap milik Kahf. |
| — `MENTHOL` | **OCR Typo:** Terbaca sebagai `DIMETHICONE`. |
| — `ETHYLHEXYLGLYCERIN` | **OCR Typo:** Terbaca sebagai `GLYCERIN` (sufiks `ETHYLHEXYL-` di awal terlewat). |
| — `MENTHYL LACTATE` | **OCR Typo:** Terbaca sebagai `DIMETHICONE` (sama seperti `MENTHOL`, nama bahan dengan `MENTH-` kerap tertukar). |
| — `PEG-40 HYDROGENATED CASTOR OIL` | **OCR Typo:** Terbaca sebagai `PEG-4O CASTOR OIL` (angka `40` terbaca `4O` — huruf O vs angka 0, dan kata `HYDROGENATED` hilang). |
| — `CITRIC ACID` | **OCR Typo:** Terbaca sebagai `STEARIC ACID`. |
| — `SODIUM CITRATE`, `SODIUM BENZOATE` | **OCR Typo (Terpotong):** Keduanya terbaca hanya sebagai `SODIUM` (sisa nama bahan terpotong, tidak cukup karakter untuk fuzzy match). |
| — `2-HEXANEDIOL`, `AMINOMETHYL PROPANEDIOL` | **OCR Typo:** Keduanya terbaca sebagai `PROPANEDIOL` (kata depan hilang). |
| — `SODIUM DEHYDROACETATE` | **OCR Typo:** Terbaca sebagai `SODIUM CAPRYLHYDROXAMIC ACID`. |
| — `CI 77891`, `CI 19140`, `CI 77266`, `CI 42090` | **Cut-off Bawah:** Semua kode warna CI (Color Index) berada di paling bawah daftar INCI, terpotong oleh batas bawah frame scan. |
| Token Noise (FP) | *(Tidak ada)* |

---

#### Produk 10 — Wardah Face Mist (`wardah_face_mist`)
| Kategori | Detail |
|:---------|:-------|
| Berhasil Dikenali | **4 / 16 bahan (25.00%)** |
| Bahan MISS (12 bahan) | `Niacinamide`, `Propanediol`, `Phenoxyethanol`, `Chlorphenesin`, `Disodium EDTA`, `Allantoin`, `Glycerin`, `PVP`, `Trideceth-9`, `PEG-Hydrogenated Castor Oil`, `Fragrance`, `Polysorbate 20` |
| Detail Penyebab MISS | |
| — `Niacinamide`, `Phenoxyethanol` | **Cut-off Atas:** Teks komposisi bagian awal terpotong/hilang batas karakternya pada pengambilan gambar. |
| — `Propanediol` | **OCR Typo (Token Gabungan):** Terbaca sebagai `PROPYLNEGLYCOL PVP` (kesalahan penggabungan token karena kurangnya koma/pemisah yang jelas). |
| — `Disodium EDTA`, `Allantoin` | **OCR Typo Parah:** Terbaca sebagai blok token noise `DISODIUM DTAALLANTNGLYERIN` (huruf E pada EDTA hilang menjadi DTA, tergabung dengan Allantoin dan Glycerin). |
| — `Chlorphenesin`, `Glycerin`, `PVP`, `Trideceth-9` | **Gagal terdeteksi:** Teks tertutup oleh distorsi atau tergabung dalam blok token yang salah terbaca. |
| — `PEG-Hydrogenated Castor Oil`, `Fragrance`, `Polysorbate 20` | **Cut-off Bawah:** Berada di ujung akhir daftar komposisi, terpotong oleh batas bawah frame kamera saat pengambilan gambar. |
| Token Noise (FP) | `DISODIUM DTAALLANTNGLYERIN` (blok token gabungan yang cacat akibat hilangnya pemisah koma) |

---

## Kategorisasi Penyebab Miss Bahan (Rekap Lintas Skenario)

Berdasarkan seluruh data dari Skenario 1 dan Skenario 2, terdapat **3 kategori utama** penyebab kegagalan sistem OCR dalam mengenali bahan kosmetik:

### Kategori A — OCR Typo / Substitusi Karakter
Bahan terdeteksi oleh OCR tetapi nama yang terbaca tidak mencapai ambang batas kemiripan *fuzzy* ≥ 0.72 terhadap nama bahan asli (*Ground Truth*).

**Faktor Penyebab:** Resolusi kamera rendah, kontras lemah, ukuran font kecil, kelengkungan/glare permukaan kemasan.

**Contoh:**
- `CETEARYL OLIVATE` → terbaca `SORBITAN OLIVATE`
- `BUTYLENE GLYCOL` → terbaca `PROPYLENE GLYCOL`
- `MYRISTIC ACID` → terbaca `PALMITIC ACID`
- `BIFIDA FERMENT LYSATE` → terbaca `LACTOCOCCUS FERMENT LYSATE`

---

### Kategori B — Terpotong / Cut-off (Batas Frame)
Bahan tidak muncul sama sekali dalam output OCR karena area teks di pinggiran atas atau bawah kemasan tidak masuk ke dalam *bounding box* pengambilan gambar oleh pengguna.

**Faktor Penyebab:** Pengambilan gambar kurang presisi; bagian teks komposisi di tepi atas/bawah label terpotong oleh batas frame kamera.

**Contoh:**
- `AQUA` pada Facial Wash G2G (posisi paling atas daftar INCI)
- `CI 77891`, `CI 77266`, dst. pada Facial Wash Kahf (posisi paling bawah daftar INCI)
- `AROMA` pada beberapa produk (sering menjadi bahan terakhir dalam daftar)

---

### Kategori C — Penggabungan Token / Merged Tokens (Missing Delimiter)
Dua atau lebih bahan tergabung menjadi satu token panjang karena koma/pemisah antar bahan tidak terdeteksi oleh OCR, atau memang tidak ada koma pada desain kemasan.

**Faktor Penyebab:** Format kemasan tanpa tanda koma; baris-baris teks melengkung pada botol silinder menyebabkan koma tidak terbaca; noise pada kemasan premium/gelap.

**Contoh:**
- `POTASSIUM SORBATE | SODIUM BENZOATE` → terbaca `POTASSIUM SORBATEABCDEF EDTA` (satu blok)
- `1,2-HEXANEDIOL` → terpecah menjadi token `1` dan `2-HEXANEDIOL` (koma dianggap pemisah daftar)
- `BUTYROSPERMUM PARKII BUTTER + CITRULLUS LANATUS + AROMA + PENTAERYTHRITYL...` → satu token raksasa pada Lipcare Madame Gie

---

## File Output Data Laporan

| Skenario | File CSV | Keterangan |
|:---------|:---------|:-----------|
| Skenario 1 | [missed_ingredients_skenario_1.csv](file:///C:/Kuliah%20Ardan/TA/Sistem/skincare-analyzer-backend/ocr_evaluation/results/missed_ingredients_skenario_1.csv) | 11 trial G2G Cleanser, 16 bahan GT |
| Skenario 2 | [missed_ingredients_skenario_2.csv](file:///C:/Kuliah%20Ardan/TA/Sistem/skincare-analyzer-backend/ocr_evaluation/results/missed_ingredients_skenario_2.csv) | 9 produk berbeda merek, total 298 bahan GT |

Kedua file CSV berisi kolom: `Kode Sample`, `Nama Produk`, `Engine OCR`, `Total Bahan Asli (GT)`, `Total Berhasil Dikenali`, `Total Miss`, `Total False Positives`, `Daftar Bahan MISS`, `Detail Penyebab MISS`, dan `Daftar Token Salah (False Positives)`.
