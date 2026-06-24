#!/usr/bin/env python3
"""
Script untuk memasukkan data ke Qdrant di VPS.

CARA TERBAIK (hemat RAM, tanpa Docker Qdrant):
  Gunakan endpoint /admin/reingest dari backend yang sudah jalan.
  Backend berjalan dalam proses yang sama → tidak ada konflik file lock.

  curl -X POST http://localhost:8000/admin/reingest \
       -H "X-Api-Key: YOUR_MONITORING_KEY"

  Ganti YOUR_MONITORING_KEY dengan nilai MONITORING_API_KEY di .env

CARA ALTERNATIF (jika backend belum jalan):
  Stop backend dulu, jalankan script ini, lalu start ulang:

  docker-compose stop backend
  python3 scripts/ingest_qdrant.py
  docker-compose start backend

  JANGAN jalankan script ini saat backend sedang berjalan!
  File lock Qdrant tidak bisa diakses dua proses sekaligus.
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

from modules.qdrant_client_factory import get_qdrant_mode
from modules.qdrant_setup import setup_qdrant

if __name__ == "__main__":
    print("=" * 60)
    print("  Skincare Analyzer — Qdrant Ingestion Script")
    print("=" * 60)
    print()
    print("⚠️  PERINGATAN: Script ini hanya boleh dijalankan saat")
    print("    backend TIDAK sedang berjalan!")
    print()
    print("💡 Cara yang lebih baik (tanpa stop backend):")
    monitoring_key = os.getenv("MONITORING_API_KEY", "YOUR_MONITORING_KEY")
    print(f"    curl -X POST http://localhost:8000/admin/reingest \\")
    print(f"         -H 'X-Api-Key: {monitoring_key}'")
    print()
    print(f"Mode Qdrant  : {get_qdrant_mode()}")
    print()
    print("Dataset yang akan di-load:")
    print("  - cosmetic_ingredients.csv")
    print("  - ingredients_category.csv")
    print("  - BPOM harmful CSV")
    print("  - incidecoder_ingredients.csv")
    print("  - incidecoder_products.csv")
    print("  - incidecoder_product_ingredients.csv  ← relasi bahan-produk")
    print()

    resp = input("Lanjutkan? Backend sudah di-stop? (y/N): ").strip().lower()
    if resp != "y":
        print("Dibatalkan.")
        sys.exit(0)

    print("\nMulai proses ingestion...\n")
    setup_qdrant()

    print()
    print("=" * 60)
    print("✅ Ingestion selesai!")
    print("=" * 60)
    print()
    print("Langkah selanjutnya:")
    print("  docker-compose start backend")
    print("  curl 'http://localhost:8000/recommendations?ingredients=Glycerin,Niacinamide'")
