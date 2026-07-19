from sqlalchemy import create_engine, text
from database.db_connection import DATABASE_URL

engine = create_engine(DATABASE_URL)
try:
    with engine.begin() as conn:
        print("Mulai pembersihan data sampah (dangling data)...")
        # Hapus data sampah
        res1 = conn.execute(text("DELETE FROM scans WHERE product_id IS NULL"))
        print(f"- {res1.rowcount} riwayat scan tanpa produk dihapus.")
        
        res2 = conn.execute(text("DELETE FROM products WHERE name IS NULL"))
        print(f"- {res2.rowcount} produk tanpa nama dihapus.")
        
        print("\nMulai standarisasi nilai NULL...")
        # Update tabel analyses
        conn.execute(text("UPDATE analyses SET overall_score = 0 WHERE overall_score IS NULL"))
        conn.execute(text("UPDATE analyses SET classification = 'Unknown' WHERE classification IS NULL"))
        conn.execute(text("UPDATE analyses SET ai_model = 'unknown' WHERE ai_model IS NULL"))
        conn.execute(text("UPDATE analyses SET ai_output = '' WHERE ai_output IS NULL"))
        conn.execute(text("UPDATE analyses SET raw_result = '{}' WHERE raw_result IS NULL"))
        print("- Tabel analyses selesai di-update.")
        
        # Update tabel products
        conn.execute(text("UPDATE products SET category = 'Lainnya' WHERE category IS NULL"))
        conn.execute(text("UPDATE products SET description = '' WHERE description IS NULL"))
        conn.execute(text("UPDATE products SET image_url = '' WHERE image_url IS NULL"))
        conn.execute(text("UPDATE products SET barcode = '' WHERE barcode IS NULL"))
        print("- Tabel products selesai di-update.")
        
        # Update tabel scan_ingredients
        conn.execute(text("UPDATE scan_ingredients SET match_confidence = 0.0 WHERE match_confidence IS NULL"))
        print("- Tabel scan_ingredients selesai di-update.")
        
        # Update tabel scans
        conn.execute(text("UPDATE scans SET image_url = '' WHERE image_url IS NULL"))
        print("- Tabel scans selesai di-update.")
        
        # Update tabel users (Kecuali reset_otp dan reset_otp_expires_at)
        conn.execute(text("UPDATE users SET provider = 'manual' WHERE provider IS NULL"))
        conn.execute(text("UPDATE users SET firebase_uid = '' WHERE firebase_uid IS NULL"))
        conn.execute(text("UPDATE users SET profile_picture = '' WHERE profile_picture IS NULL"))
        conn.execute(text("UPDATE users SET fcm_token = '' WHERE fcm_token IS NULL"))
        conn.execute(text("UPDATE users SET device_token = '' WHERE device_token IS NULL"))
        print("- Tabel users selesai di-update.")
        
        print("\nPembersihan dan standarisasi selesai dengan sukses!")
except Exception as e:
    print(f"Error: {e}")
