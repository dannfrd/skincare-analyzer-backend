## Notifikasi FCM (Firebase Cloud Messaging)

Untuk mengirim notifikasi ke semua user mobile:

```
from modules.fcm_notification import send_notification_to_all

# Contoh pengiriman notifikasi
send_notification_to_all(
	title="Update Aplikasi!",
	body="Ada fitur baru, yuk update aplikasi kamu!",
	data={"type": "update", "url": "https://playstore.link"}
)
```

Pastikan aplikasi mobile subscribe ke topic 'all'.
# Skincare Analyzer Backend (FastAPI)

Backend ini menerima teks/gambar ingredient dari Flutter, melakukan OCR + cleaning + matching ingredient + AI analysis, lalu menyimpan hasil ke MySQL.

## 1) Prasyarat

- Python 3.10+ (disarankan 3.11+)
- MySQL server aktif (Laragon/XAMPP/MySQL standalone)
- Tesseract OCR terpasang (wajib untuk endpoint gambar)

## 2) Setup Environment Python

Masuk ke folder backend:

```bash
cd skincare-analyzer-backend
```

Buat virtual environment:

```bash
python -m venv .venv
```

Aktifkan venv (Windows CMD/PowerShell):

```bash
.venv\Scripts\activate
```

Install dependency:

```bash
pip install -r requirements.txt
```

Jika belum ada paket FastAPI runtime, install juga:

```bash
pip install fastapi uvicorn python-multipart
```

## 3) Konfigurasi Environment Variable

Buat file `.env` di root backend:

```env
DB_HOST=localhost
DB_USER=root
DB_PASSWORD=
DB_NAME=skincare_analyzer

GEMINI_API_KEY=isi_api_key_gemini_kamu
MONITORING_API_KEY=opsional_api_key_monitoring
```

Catatan:
- `DB_*` dipakai oleh `database/db_connection.py`.
- `GEMINI_API_KEY` dipakai oleh `modules/gemini_ai.py`.
- `MONITORING_API_KEY` dipakai untuk endpoint monitoring (`/health`, `/metrics/*`).

## 4) Setup Database MySQL

Pastikan MySQL running dan database tersedia:

```sql
CREATE DATABASE IF NOT EXISTS skincare_analyzer;
USE skincare_analyzer;

CREATE TABLE IF NOT EXISTS ingredients (
	id INT AUTO_INCREMENT PRIMARY KEY,
	inci_name VARCHAR(255) NOT NULL,
	is_allergen TINYINT(1) DEFAULT 0,
	unsafe_for_pregnancy TINYINT(1) DEFAULT 0,
	comedogenic_rating INT DEFAULT 0,
	updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS analysis_results (
	id INT AUTO_INCREMENT PRIMARY KEY,
	raw_text TEXT,
	ai_analysis JSON,
	created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);
```

Isi data `ingredients` sesuai dataset yang kamu pakai, karena proses matching mengambil data dari tabel ini.

## 5) Menjalankan FastAPI

Jalankan server:

```bash
uvicorn main:app --reload --host 0.0.0.0 --port 8000
```

Kenapa `0.0.0.0`:
- supaya backend bisa diakses emulator dan HP fisik di jaringan LAN.

## 6) Cek Endpoint Dasar

- Root:

```bash
curl http://127.0.0.1:8000/
```

- Health (jika `MONITORING_API_KEY` diisi):

```bash
curl -H "x-api-key: isi_api_key_monitoring" http://127.0.0.1:8000/health
```

- Docs FastAPI:

```text
http://127.0.0.1:8000/docs
```

## 7) Integrasi dengan Flutter (Real Device)

Jalankan Flutter dengan base URL LAN:

```bash
flutter run --dart-define=API_BASE_URL=http://192.168.1.10:8000
```

Pastikan:
- HP dan laptop satu Wi-Fi
- IP LAN valid (contoh valid `192.168.1.10`)
- Port 8000 terbuka di firewall

## 8) Troubleshooting

### Error koneksi database (contoh WinError 10061)

Penyebab umum:
- service MySQL belum jalan
- host/user/password/database di `.env` salah

Langkah cek cepat:
1. Pastikan service MySQL running.
2. Tes login manual ke MySQL dengan credential yang sama.
3. Cek apakah database `skincare_analyzer` ada.

### `/` sukses, tapi `/analyze` atau `/analyze-image` gagal

Biasanya karena query ke MySQL gagal (database belum siap) atau tabel belum ada.

### OCR gagal (`tesseract not found`)

Install Tesseract OCR dan pastikan executable-nya ada di PATH OS.

### Endpoint monitoring 401 Unauthorized

Pastikan header `x-api-key` sesuai `MONITORING_API_KEY`.

