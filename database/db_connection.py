import os
import json
import logging
from datetime import datetime
from typing import List, Dict, Any, Optional

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

    def ping(self) -> bool:
        """Checks whether the database connection is alive."""
        if not self.engine:
            return False

        try:
            with self.engine.connect() as conn:
                conn.execute(text("SELECT 1"))
            return True
        except Exception as e:
            logger.error(f"Database ping failed: {e}")
            return False

    def get_analysis_summary(self) -> Dict[str, Any]:
        """Returns aggregate analytics about analysis_results table."""
        summary = {
            "total": 0,
            "last_24h": 0,
            "last_7d": 0,
            "average_per_day": 0,
            "last_created_at": None,
        }

        if not self.engine:
            return summary

        try:
            with self.engine.connect() as conn:
                totals = conn.execute(text(
                    """
                    SELECT COUNT(*) AS total,
                           MAX(created_at) AS last_created,
                           MIN(created_at) AS first_created
                    FROM analysis_results
                    """
                )).mappings().first()

                if totals:
                    summary["total"] = totals.get("total", 0) or 0
                    last_created = totals.get("last_created")
                    first_created = totals.get("first_created")
                    summary["last_created_at"] = (
                        last_created.isoformat() if isinstance(last_created, datetime) else None
                    )

                    if first_created and isinstance(first_created, datetime):
                        days_span = max((datetime.now(first_created.tzinfo) - first_created).days + 1, 1)
                        if days_span:
                            summary["average_per_day"] = round(summary["total"] / days_span, 2)

                last_24h = conn.execute(text(
                    """
                    SELECT COUNT(*) AS count FROM analysis_results
                    WHERE created_at >= NOW() - INTERVAL 1 DAY
                    """
                )).scalar()

                last_7d = conn.execute(text(
                    """
                    SELECT COUNT(*) AS count FROM analysis_results
                    WHERE created_at >= NOW() - INTERVAL 7 DAY
                    """
                )).scalar()

                summary["last_24h"] = last_24h or 0
                summary["last_7d"] = last_7d or 0
        except Exception as e:
            logger.error(f"Error building analysis summary: {e}")

        return summary

    def get_recent_analysis_results(self, limit: int = 15) -> List[Dict[str, Any]]:
        """Returns the most recent analysis result rows."""
        if not self.engine:
            return []

        limit = max(1, min(limit, 100))

        try:
            query = text(
                """
                SELECT id, raw_text, ai_analysis, created_at
                FROM analysis_results
                ORDER BY created_at DESC
                LIMIT :limit
                """
            )

            records: List[Dict[str, Any]] = []
            with self.engine.connect() as conn:
                for row in conn.execute(query, {"limit": limit}).mappings():
                    ai_payload: Optional[Any] = row.get("ai_analysis")
                    if isinstance(ai_payload, str):
                        try:
                            ai_payload = json.loads(ai_payload)
                        except json.JSONDecodeError:
                            pass

                    created_at = row.get("created_at")
                    records.append({
                        "id": row.get("id"),
                        "raw_text": row.get("raw_text"),
                        "ai_analysis": ai_payload,
                        "created_at": created_at.isoformat() if isinstance(created_at, datetime) else None,
                    })

            return records
        except Exception as e:
            logger.error(f"Error fetching recent analysis results: {e}")
            return []

    def get_ingredient_summary(self) -> Dict[str, Any]:
        """Returns risk-oriented counts from the ingredients table."""
        summary = {
            "total": 0,
            "allergens": 0,
            "unsafe_for_pregnancy": 0,
            "high_comedogenic": 0,
            "average_comedogenic_rating": None,
            "last_updated_at": None,
        }

        if not self.engine:
            return summary

        try:
            with self.engine.connect() as conn:
                stats = conn.execute(text(
                    """
                    SELECT COUNT(*) AS total,
                           SUM(CASE WHEN is_allergen = 1 THEN 1 ELSE 0 END) AS allergens,
                           SUM(CASE WHEN unsafe_for_pregnancy = 1 THEN 1 ELSE 0 END) AS unsafe,
                           SUM(CASE WHEN comedogenic_rating >= 4 THEN 1 ELSE 0 END) AS high_comedogenic,
                           AVG(comedogenic_rating) AS avg_comedogenic,
                           MAX(updated_at) AS last_updated
                    FROM ingredients
                    """
                )).mappings().first()

                if stats:
                    summary["total"] = stats.get("total", 0) or 0
                    summary["allergens"] = stats.get("allergens", 0) or 0
                    summary["unsafe_for_pregnancy"] = stats.get("unsafe", 0) or 0
                    summary["high_comedogenic"] = stats.get("high_comedogenic", 0) or 0
                    avg_rating = stats.get("avg_comedogenic")
                    summary["average_comedogenic_rating"] = float(avg_rating) if avg_rating is not None else None
                    last_updated = stats.get("last_updated")
                    summary["last_updated_at"] = (
                        last_updated.isoformat() if isinstance(last_updated, datetime) else None
                    )
        except Exception as e:
            logger.error(f"Error building ingredient summary: {e}")

        return summary

# Helper untuk mendapatkan instance dari koneksi database
def get_db_connection() -> DatabaseConnection:
    return DatabaseConnection()
