import os
import logging
from typing import List, Dict, Any
from sqlalchemy import create_engine, text
from dotenv import load_dotenv

# Load environment variables (e.g., dari .env file)
load_dotenv()

logger = logging.getLogger(__name__)

# Konfigurasi Database untuk MySQL (Laragon default)
DB_HOST = os.getenv("DB_HOST", "localhost")
DB_USER = os.getenv("DB_USER", "root")
DB_PASSWORD = os.getenv("DB_PASSWORD", "")
DB_NAME = os.getenv("DB_NAME", "skincare_analyzer")

# Connection string menggunakan PyMySQL
DATABASE_URL = f"mysql+pymysql://{DB_USER}:{DB_PASSWORD}@{DB_HOST}/{DB_NAME}"

class DatabaseConnection:
    """
    Handles connection to the MySQL database.
    """
    
    def __init__(self):
        try:
            # Setup SQLAlchemy engine
            self.engine = create_engine(DATABASE_URL, pool_recycle=3600)
            logger.info(f"Connected to MySQL Database: {DB_NAME} at {DB_HOST}")
        except Exception as e:
            logger.error(f"Failed to connect to MySQL database: {e}")
            self.engine = None

    def get_all_ingredients(self) -> List[Dict[str, Any]]:
        """
        Returns the full list of known ingredients from the 'ingredients' table.
        Used for ingredient matching.
        """
        if not self.engine:
            logger.error("No database connection available.")
            return []
            
        try:
            with self.engine.connect() as conn:
                # Ambil semua data dari table ingredients
                result = conn.execute(text("SELECT * FROM ingredients"))
                # Ubah rows menjadi list of dictionaries
                return [dict(row._mapping) for row in result]
        except Exception as e:
            logger.error(f"Error fetching ingredients from database: {e}")
            return []

    def save_analysis_result(self, raw_text: str, ai_result: dict) -> int:
        """
        Menyimpan hasil analisis ke tabel 'analysis_results'.
        Note: Sesuaikan query structure dengan field yang ada di tabel kamu.
        """
        if not self.engine:
            return None

        try:
            with self.engine.begin() as conn: # .begin() auto commits
                # Contoh insert ke tabel analysis_results
                # Sesuaikan nama kolom dengan struktur tabel kamu di Laragon
                query = text("""
                    INSERT INTO analysis_results (raw_text, ai_analysis, created_at)
                    VALUES (:raw_text, :ai_analysis, NOW())
                """)
                
                # Menggunakan json.dumps() jika ai_result perlu disimpan sebagai JSON string
                import json
                result = conn.execute(query, {
                    "raw_text": raw_text,
                    "ai_analysis": json.dumps(ai_result)
                })
                # Mengembalikan ID dari baris yang baru saja ditambahkan
                return result.lastrowid
        except Exception as e:
            logger.error(f"Error saving analysis result: {e}")
            return None

# Helper untuk mendapatkan instance dari koneksi database
def get_db_connection() -> DatabaseConnection:
    return DatabaseConnection()
