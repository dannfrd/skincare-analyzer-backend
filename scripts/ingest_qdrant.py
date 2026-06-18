#!/usr/bin/env python3
"""
Script untuk memasukkan data ke Qdrant di VPS.

Usage (di VPS setelah upload dataset baru):
    python scripts/ingest_qdrant.py

Script ini akan:
1. Load semua dataset (ingredients, categories, BPOM, incidecoder + relasi produk)
2. Buat/recreate Qdrant collection 'skincare_ingredients'
3. Generate embeddings untuk setiap ingredient
4. Simpan ke Qdrant (file-local mode di qdrant_data/)

Cara cek mode Qdrant di VPS:
    ls ~/skincare-analyzer-backend/qdrant_data/   # kalau ada = mode lokal (ini yang dipakai)
    ss -tlnp | grep 6333                           # kalau ada = Qdrant server terpisah

Untuk cek apakah Qdrant server berjalan (HTTP mode):
    curl http://localhost:6333/collections         # kalau OK = server mode
"""

import os
import sys

# Tambahkan root project ke path agar module imports bekerja
script_dir = os.path.dirname(os.path.abspath(__file__))
project_root = os.path.dirname(script_dir)
sys.path.insert(0, project_root)

# Load .env sebelum import modules
try:
    from dotenv import load_dotenv
    load_dotenv(os.path.join(project_root, ".env"))
    print("✅ .env loaded")
except ImportError:
    print("⚠️  python-dotenv not installed, skipping .env load")

from modules.qdrant_setup import setup_qdrant

if __name__ == "__main__":
    print("=" * 60)
    print("  Skincare Analyzer — Qdrant Ingestion Script")
    print("=" * 60)
    print()
    print("Dataset yang akan di-load:")
    print("  - cosmetic_ingredients.csv")
    print("  - ingredients_category.csv")
    print("  - BPOM harmful CSV")
    print("  - incidecoder_ingredients.csv  (+ inci_id per bahan)")
    print("  - incidecoder_products.csv")
    print("  - incidecoder_product_ingredients.csv  ← BARU (relasi)")
    print()
    print("Mulai proses ingestion...\n")
    
    setup_qdrant()
    
    print()
    print("=" * 60)
    print("✅ Ingestion selesai!")
    print("=" * 60)
    print()
    print("Langkah selanjutnya:")
    print("  1. Restart backend: sudo systemctl restart skincare-backend")
    print("     atau: docker-compose restart backend")
    print("  2. Test endpoint: curl 'http://localhost:8000/recommendations?ingredients=Glycerin,Niacinamide'")
    print("  3. Cek mode yang digunakan di response field 'mode_used'")
