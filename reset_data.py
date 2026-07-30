import os
import logging
from sqlalchemy import create_engine, text
from database.db_connection import DATABASE_URL

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

def reset_tables():
    engine = create_engine(DATABASE_URL)
    
    tables_to_truncate = [
        "user_histories",
        "scan_ingredients",
        "analyses",
        "scans",
        "notifications",
        "products"
    ]
    
    try:
        with engine.begin() as conn:
            print("Mempersiapkan penghapusan data...")
            # Disable foreign key checks to safely truncate tables with relations
            conn.execute(text("SET FOREIGN_KEY_CHECKS = 0;"))
            
            for table in tables_to_truncate:
                conn.execute(text(f"TRUNCATE TABLE {table};"))
                print(f"✅ Tabel '{table}' berhasil dikosongkan.")
            
            # Re-enable foreign key checks
            conn.execute(text("SET FOREIGN_KEY_CHECKS = 1;"))
            print("\n🎉 Pembersihan data berhasil! Semua history, notifikasi, dan produk sudah kembali bersih (kosong).")
            
    except Exception as e:
        print(f"❌ Terjadi kesalahan: {e}")
        # Try to re-enable foreign key checks if it failed midway
        try:
            with engine.begin() as conn:
                conn.execute(text("SET FOREIGN_KEY_CHECKS = 1;"))
        except:
            pass

if __name__ == "__main__":
    reset_tables()
