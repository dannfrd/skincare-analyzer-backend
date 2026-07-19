import os
from sqlalchemy import create_engine, text
from database.db_connection import DATABASE_URL

engine = create_engine(DATABASE_URL)

try:
    with engine.begin() as conn:
        print("Mulai proses refresh database...")
        
        # 1. Hapus relasi turunan dari scans
        print("Menghapus data analyses dan details...")
        conn.execute(text("DELETE FROM analysis_details"))
        conn.execute(text("DELETE FROM analyses"))
        conn.execute(text("DELETE FROM scan_ingredients"))
        
        # 2. Hapus history dan scans
        print("Menghapus data history dan scans...")
        conn.execute(text("DELETE FROM user_histories"))
        conn.execute(text("DELETE FROM scans"))
        
        # 3. Hapus notifikasi
        print("Menghapus notifikasi...")
        conn.execute(text("DELETE FROM notifications"))
        
        # 4. Hapus products (karena diminta hapus 'lainnya')
        print("Menghapus products...")
        conn.execute(text("DELETE FROM products"))
        
        # 5. Hapus semua user KECUALI admin
        print("Menghapus semua user kecuali Dermify Administrator...")
        res = conn.execute(text("DELETE FROM users WHERE email != 'dermify@gmail.com'"))
        print(f"- {res.rowcount} user biasa dihapus.")
        
        print("\nRefresh database selesai! Database Anda sekarang benar-benar fresh.")
        print("Data yang tersisa hanyalah User Admin, Ingredients, dan Product Categories.")
        
except Exception as e:
    print(f"Terjadi kesalahan: {e}")
