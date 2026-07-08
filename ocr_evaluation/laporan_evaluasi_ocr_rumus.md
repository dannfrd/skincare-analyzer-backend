# Rumus dan Metrik Evaluasi Pengenalan Teks (OCR) untuk Laporan Tugas Akhir

Dokumen ini memuat rumusan matematis, definisi, serta metodologi evaluasi kinerja sistem *Optical Character Recognition* (OCR) dalam mendeteksi dan mengekstrak daftar komposisi bahan kosmetik (*skincare ingredients*). Rumus-rumus ini disiapkan untuk dimasukkan ke dalam Bab Metodologi / Bab Pengujian Laporan Tugas Akhir (TA).

---

## 1. Jarak Edit Levenshtein (*Levenshtein Distance*)

Algoritma dasar yang digunakan untuk menghitung tingkat kesalahan karakter maupun kata adalah **Levenshtein Distance**. Jarak Levenshtein $LD(X, Y)$ antara string/sekuens $X$ dengan panjang $m$ dan sekuens $Y$ dengan panjang $n$ dihitung melalui pemrograman dinamis (*dynamic programming*) sebagai berikut:

$$
LD(i,j) = \begin{cases} 
\max(i, j) & \text{jika } \min(i, j) = 0 \\
\min \big( LD(i-1, j) + 1, \; LD(i, j-1) + 1, \; LD(i-1, j-1) + \mathbb{I}(x_i \neq y_j) \big) & \text{lainnya}
\end{cases}
$$

**Keterangan:**
- $LD_{i-1, j} + 1$ mewakili operasi **penghapusan (*Deletion*)**.
- $LD_{i, j-1} + 1$ mewakili operasi **penyisipan (*Insertion*)**.
- $LD_{i-1, j-1} + \mathbb{I}(x_i \neq y_j)$ mewakili operasi **substitusi (*Substitution*)**, di mana $\mathbb{I}(x_i \neq y_j) = 1$ jika elemen ke-$i$ pada sekuens asli berbeda dengan elemen ke-$j$ pada keluaran OCR, dan bernilai $0$ jika sama.

---

## 2. Tingkat Kesalahan Karakter (*Character Error Rate* / CER)

CER mengukur persentase kesalahan karakter yang dihasilkan oleh engine OCR dibandingkan dengan teks asli (*Ground Truth*).

$$
\text{CER} = \frac{S + D + I}{N} = \frac{LD(\text{Char}_{GT}, \text{Char}_{OCR})}{\text{Total Karakter}_{GT}} \times 100\%
$$

**Keterangan:**
- $S$ = Jumlah karakter yang diganti (*Substitutions*)
- $D$ = Jumlah karakter yang hilang/terhapus (*Deletions*)
- $I$ = Jumlah karakter yang tersisip (*Insertions*)
- $N$ = Total jumlah karakter pada *Ground Truth* ($N = S + D + C$, di mana $C$ adalah karakter yang benar)

> [!NOTE]
> Semakin rendah nilai **CER**, semakin akurat pengenalan karakter oleh sistem OCR. Nilai CER ideal adalah mendekati $0\%$.

---

## 3. Tingkat Kesalahan Kata (*Word Error Rate* / WER)

WER mengukur persentase kesalahan pada tingkat kata dengan memperlakukan setiap kata sebagai satu unit token.

$$
\text{WER} = \frac{S_w + D_w + I_w}{N_w} = \frac{LD(\text{Word}_{GT}, \text{Word}_{OCR})}{\text{Total Kata}_{GT}} \times 100\%
$$

**Keterangan:**
- $S_w, D_w, I_w$ = Substitusi, Deletion, dan Insertion pada tingkat kata
- $N_w$ = Total jumlah kata pada teks *Ground Truth*

---

## 4. Akurasi Pencocokan Komposisi (*Exact Match Evaluation*)

Setelah keluaran teks OCR diproses oleh *Text Cleaning Pipeline* menjadi senarai token komposisi individu, akurasi pencocokan persis (*Exact Match*) dihitung berdasarkan matriks *Precision*, *Recall*, dan *F1-Score*.

### a. Precision (*Exact*)
Mengukur seberapa banyak token komposisi yang diekstrak oleh OCR benar-benar merupakan bahan kosmetik yang valid sesuai *Ground Truth*.

$$
\text{Precision}_{\text{exact}} = \frac{\text{TP}_{\text{exact}}}{\text{TP}_{\text{exact}} + \text{FP}_{\text{exact}}} \times 100\%
$$

### b. Recall (*Exact*)
Mengukur seberapa banyak bahan kosmetik pada *Ground Truth* yang berhasil diekstrak dan dicocokkan secara sempurna oleh sistem OCR.

$$
\text{Recall}_{\text{exact}} = \frac{\text{TP}_{\text{exact}}}{\text{TP}_{\text{exact}} + \text{FN}_{\text{exact}}} \times 100\%
$$

### c. F1-Score (*Exact*)
Rata-rata harmonis antara Precision dan Recall Exact.

$$
\text{F1-Score}_{\text{exact}} = 2 \times \frac{\text{Precision}_{\text{exact}} \times \text{Recall}_{\text{exact}}}{\text{Precision}_{\text{exact}} + \text{Recall}_{\text{exact}}}
$$

---

## 5. Akurasi Pencocokan Toleran (*Fuzzy Match Evaluation*)

Karena teks pada label kemasan sering kali mengalami salah baca karakter minor oleh OCR (misalnya karakter `l` dibaca `I`, atau hilangnya spasi), pencocokan persis (*Exact Match*) kerap menghasilkan akurasi $0\%$. Oleh karena itu, digunakan **Fuzzy Match Evaluation** menggunakan algoritma *Approximate String Matching* dengan ambang batas kemiripan (*similarity cutoff threshold*) sebesar $\theta = 0.72$ (72%) serta pengujian *substring*.

Fungsi rasio kemiripan dua token komposisi $T_{\text{ocr}}$ dan $T_{\text{gt}}$ didefinisikan sebagai:

$$
\text{Similarity}(T_{\text{ocr}}, T_{\text{gt}}) = \frac{2 \times M}{|T_{\text{ocr}}| + |T_{\text{gt}}|}
$$

Di mana $M$ adalah jumlah karakter yang cocok (*matching characters*) dalam sekuens terpanjang. Suatu token OCR $T_{\text{ocr}}$ dinyatakan sebagai *True Positive* Fuzzy ($\text{TP}_{\text{fuzzy}}$) apabila memenuhi syarat:

$$
\max_{T_{\text{gt}} \in \text{GT}} \text{Similarity}(T_{\text{ocr}}, T_{\text{gt}}) \geq 0.72 \quad \lor \quad (T_{\text{ocr}} \subseteq T_{\text{gt}} \lor T_{\text{gt}} \subseteq T_{\text{ocr}})
$$

Rumus perhitungannya adalah:

$$
\text{Precision}_{\text{fuzzy}} = \frac{\text{TP}_{\text{fuzzy}}}{|T_{\text{ocr}}|} \times 100\%
$$

$$
\text{Recall}_{\text{fuzzy}} = \frac{|\text{Matched GT}|}{|\text{GT}|} \times 100\%
$$

$$
\text{F1-Score}_{\text{fuzzy}} = 2 \times \frac{\text{Precision}_{\text{fuzzy}} \times \text{Recall}_{\text{fuzzy}}}{\text{Precision}_{\text{fuzzy}} + \text{Recall}_{\text{fuzzy}}}
$$

---

## 6. Efisiensi Waktu Komputasi (*Latency Performance*)

Untuk mengukur kelayakan implementasi pada sistem *real-time*, dicatat waktu eksekusi proses OCR per sampel ($\Delta t$) dalam milidetik (ms):

$$
\text{Latency (ms)} = (t_{\text{end}} - t_{\text{start}}) \times 1000
$$

Di mana $t_{\text{start}}$ adalah waktu saat gambar mulai diproses oleh engine OCR, dan $t_{\text{end}}$ adalah waktu saat teks selesai diekstrak. Rata-rata waktu eksekusi dari $K$ pengujian dirumuskan sebagai:

$$
\overline{\text{Latency}} = \frac{1}{K} \sum_{k=1}^{K} \text{Latency}_k
$$

---

## 7. Daftar Referensi & Sumber Standar Internasional (Untuk Pertanggungjawaban Akademis)

Agar rumusan dan metodologi evaluasi di atas dapat dipertanggungjawabkan secara ilmiah saat sidang atau bimbingan Tugas Akhir, berikut adalah sumber referensi formal dan publikasi internasional yang menjadi landasan standar perhitungan parameter OCR dan NLP:

### a. Referensi Levenshtein Distance, CER, dan WER
1. **NIST (National Institute of Standards and Technology) - SCTK Standard**  
   Standar internasional evaluasi pengenalan teks dan suara (termasuk rumusan baku *Word Error Rate* dan *Character Error Rate*).  
   *Tautan Resmi:* [NIST Speech Recognition Scoring Package (SCTK)](https://github.com/usnistgov/SCTK) | [NIST Standard Reference Data](https://www.nist.gov/)
2. **Hugging Face Evaluate Metric (CER & WER Documentation)**  
   Dokumentasi resmi implementasi metrik evaluasi CER dan WER pada model *Optical Character Recognition* modern dan *Natural Language Processing*.  
   *Tautan Resmi:* [Hugging Face CER Documentation](https://huggingface.co/spaces/evaluate-metric/cer) | [Hugging Face WER Documentation](https://huggingface.co/spaces/evaluate-metric/wer)
3. **Formal Definition of Levenshtein Distance (Vladimir Levenshtein, 1965)**  
   Publikasi akademis asli untuk pemrograman dinamis penghitungan jarak kesalahan karakter (*insertion, deletion, substitution*).  
   *Tautan Referensi:* [Wikipedia - Levenshtein Distance Formal Definition](https://en.wikipedia.org/wiki/Levenshtein_distance)

### b. Referensi Exact Match (Precision, Recall, dan F1-Score)
4. **Scikit-Learn Machine Learning Library Standards**  
   Standar definisi matematis internasional untuk evaluasi klasifikasi dan ekstraksi informasi (*Precision, Recall, F-measure*).  
   *Tautan Resmi:* [Scikit-Learn Model Evaluation Metrics](https://scikit-learn.org/stable/modules/model_evaluation.html#precision-recall-f-measure-metrics)
5. **Stanford University - Introduction to Information Retrieval**  
   Buku referensi akademis standar Stanford NLP oleh Manning, Raghavan, & Schütze (2008) mengenai evaluasi pencocokan token pada sistem informasi.  
   *Tautan Resmi:* [Stanford NLP IR Book - Evaluation Metrics](https://nlp.stanford.edu/IR-book/html/htmledition/evaluation-in-information-retrieval-1.html)

### c. Referensi Fuzzy Match (Gestalt Pattern Matching & Similarity Cutoff)
6. **Python Official Documentation (`difflib.SequenceMatcher`)**  
   Implementasi resmi algoritma *Gestalt Pattern Matching* oleh John W. Ratcliff dan David E. Metzener (1988) untuk menghitung rasio kemiripan string $\frac{2M}{|T_1| + |T_2|}$.  
   *Tautan Resmi:* [Python Official Docs - difflib SequenceMatcher](https://docs.python.org/3/library/difflib.html#difflib.SequenceMatcher)
7. **RapidFuzzy String Matching Documentation**  
   Standar pustaka pemrosesan teks untuk penentuan ambang batas kemiripan (*similarity thresholding*) pada teks hasil ekstraksi OCR yang mengalami *noise* atau salah baca karakter ringan.  
   *Tautan Resmi:* [RapidFuzzy Documentation & Algorithms](https://rapidfuzzy.github.io/RapidFuzzy/)

### d. Referensi Waktu Komputasi & Latency
8. **IEEE Xplore Digital Library - Real-Time Systems Benchmarking**  
   Standar pengukuran kinerja waktu komputasi (*latency* dan eksekusi instruksi per milidetik) pada aplikasi *mobile* dan *embedded system*.  
   *Tautan Resmi:* [IEEE Xplore Digital Library](https://ieeexplore.ieee.org/)
