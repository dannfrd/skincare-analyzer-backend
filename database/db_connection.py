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
                # Ubah rows menjadi list of dictionaries dan pastikan key legacy tetap tersedia.
                ingredients = [dict(row._mapping) for row in result]
                for ingredient in ingredients:
                    ingredient.setdefault("comedogenic_rating", 0)
                    ingredient.setdefault("is_allergen", False)
                    ingredient.setdefault("unsafe_for_pregnancy", False)
                return ingredients
        except Exception as e:
            logger.error(f"Error fetching ingredients from database: {e}")
            return []

    def save_analysis_result(self, raw_text: str, ai_result: dict) -> Optional[int]:
        """
        Menyimpan hasil analisis.
        - Skema lama: analysis_results
        - Skema baru: scans + analyses (+ user_histories jika tersedia)
        """
        if not self.engine:
            return None

        try:
            with self.engine.begin() as conn:
                if self._table_exists(conn, "analysis_results"):
                    result = conn.execute(text(
                        """
                        INSERT INTO analysis_results (raw_text, ai_analysis, created_at)
                        VALUES (:raw_text, :ai_analysis, NOW())
                        """
                    ), {
                        "raw_text": raw_text,
                        "ai_analysis": json.dumps(ai_result),
                    })
                    return result.lastrowid

                required_tables = ["users", "scans", "analyses"]
                if not all(self._table_exists(conn, table_name) for table_name in required_tables):
                    return None

                user_id = self._ensure_system_user(conn)
                if not user_id:
                    return None

                scan_insert = conn.execute(text(
                    """
                    INSERT INTO scans (user_id, product_id, image_url, extracted_text, created_at)
                    VALUES (:user_id, NULL, NULL, :extracted_text, NOW())
                    """
                ), {
                    "user_id": user_id,
                    "extracted_text": raw_text,
                })
                scan_id = scan_insert.lastrowid

                summary_text = self._extract_ai_text(ai_result, ["summary", "ringkasan", "result"])
                recommendation_text = self._extract_ai_text(ai_result, ["recommendation", "rekomendasi", "suggestion"])

                analysis_insert = conn.execute(text(
                    """
                    INSERT INTO analyses (scan_id, summary, recommendation, status, created_at)
                    VALUES (:scan_id, :summary, :recommendation, :status, NOW())
                    """
                ), {
                    "scan_id": scan_id,
                    "summary": summary_text,
                    "recommendation": recommendation_text,
                    "status": "completed",
                })
                analysis_id = analysis_insert.lastrowid

                if self._table_exists(conn, "user_histories"):
                    conn.execute(text(
                        """
                        INSERT INTO user_histories (user_id, analysis_id, viewed_at)
                        VALUES (:user_id, :analysis_id, NOW())
                        """
                    ), {
                        "user_id": user_id,
                        "analysis_id": analysis_id,
                    })

                return analysis_id
        except Exception as e:
            logger.error(f"Error saving analysis result: {e}")
            return None

    def _extract_ai_text(self, ai_result: Dict[str, Any], keys: List[str]) -> str:
        for key in keys:
            value = ai_result.get(key)
            if isinstance(value, str) and value.strip():
                return value.strip()

        fallback = ai_result.get("ai_analysis")
        if isinstance(fallback, str):
            return fallback.strip()

        if fallback is not None:
            try:
                return json.dumps(fallback, ensure_ascii=False)
            except Exception:
                return str(fallback)

        try:
            return json.dumps(ai_result, ensure_ascii=False)
        except Exception:
            return str(ai_result)

    def _table_exists(self, conn, table_name: str) -> bool:
        result = conn.execute(text(
            """
            SELECT COUNT(*)
            FROM information_schema.tables
            WHERE table_schema = DATABASE() AND table_name = :table_name
            """
        ), {"table_name": table_name}).scalar()
        return bool(result or 0)

    def _column_exists(self, conn, table_name: str, column_name: str) -> bool:
        result = conn.execute(text(
            """
            SELECT COUNT(*)
            FROM information_schema.columns
            WHERE table_schema = DATABASE()
              AND table_name = :table_name
              AND column_name = :column_name
            """
        ), {
            "table_name": table_name,
            "column_name": column_name,
        }).scalar()
        return bool(result or 0)

    def _ensure_system_user(self, conn) -> Optional[int]:
        email = "system-monitoring@local"

        conn.execute(text(
            """
            INSERT INTO users (name, email, password, role, created_at)
            SELECT :name, :email, :password, :role, NOW()
            WHERE NOT EXISTS (
                SELECT 1 FROM users WHERE email = :email
            )
            """
        ), {
            "name": "System Monitoring",
            "email": email,
            "password": "system-monitoring",
            "role": "system",
        })

        return conn.execute(text(
            "SELECT id FROM users WHERE email = :email LIMIT 1"
        ), {"email": email}).scalar()

    @staticmethod
    def _to_iso_datetime(value: Any) -> Optional[str]:
        return value.isoformat() if isinstance(value, datetime) else None

    @staticmethod
    def _normalize_risk_level(raw_level: Any) -> str:
        value = str(raw_level or "").strip().lower()
        mapping = {
            "low": "low",
            "rendah": "low",
            "medium": "medium",
            "moderate": "medium",
            "sedang": "medium",
            "high": "high",
            "tinggi": "high",
        }
        return mapping.get(value, "unknown")

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
        """Returns aggregate analytics for analysis tables (legacy and current schema)."""
        summary = {
            "total": 0,
            "last_24h": 0,
            "last_7d": 0,
            "average_per_day": 0,
            "last_created_at": None,
            "pending": 0,
            "completed": 0,
            "failed": 0,
        }

        if not self.engine:
            return summary

        try:
            with self.engine.connect() as conn:
                if self._table_exists(conn, "analysis_results"):
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
                        summary["last_created_at"] = self._to_iso_datetime(last_created)

                        if first_created and isinstance(first_created, datetime):
                            days_span = max((datetime.now(first_created.tzinfo) - first_created).days + 1, 1)
                            if days_span:
                                summary["average_per_day"] = round(summary["total"] / days_span, 2)

                    summary["last_24h"] = conn.execute(text(
                        """
                        SELECT COUNT(*) FROM analysis_results
                        WHERE created_at >= NOW() - INTERVAL 1 DAY
                        """
                    )).scalar() or 0

                    summary["last_7d"] = conn.execute(text(
                        """
                        SELECT COUNT(*) FROM analysis_results
                        WHERE created_at >= NOW() - INTERVAL 7 DAY
                        """
                    )).scalar() or 0

                    return summary

                if not self._table_exists(conn, "analyses"):
                    return summary

                totals = conn.execute(text(
                    """
                    SELECT COUNT(*) AS total,
                           MAX(created_at) AS last_created,
                           MIN(created_at) AS first_created,
                           SUM(CASE WHEN LOWER(status) = 'pending' THEN 1 ELSE 0 END) AS pending_count,
                           SUM(CASE WHEN LOWER(status) = 'completed' THEN 1 ELSE 0 END) AS completed_count,
                           SUM(CASE WHEN LOWER(status) IN ('failed', 'error', 'rejected') THEN 1 ELSE 0 END) AS failed_count
                    FROM analyses
                    """
                )).mappings().first()

                if totals:
                    summary["total"] = totals.get("total", 0) or 0
                    summary["pending"] = totals.get("pending_count", 0) or 0
                    summary["completed"] = totals.get("completed_count", 0) or 0
                    summary["failed"] = totals.get("failed_count", 0) or 0

                    last_created = totals.get("last_created")
                    first_created = totals.get("first_created")
                    summary["last_created_at"] = self._to_iso_datetime(last_created)

                    if first_created and isinstance(first_created, datetime):
                        days_span = max((datetime.now(first_created.tzinfo) - first_created).days + 1, 1)
                        if days_span:
                            summary["average_per_day"] = round(summary["total"] / days_span, 2)

                summary["last_24h"] = conn.execute(text(
                    """
                    SELECT COUNT(*) FROM analyses
                    WHERE created_at >= NOW() - INTERVAL 1 DAY
                    """
                )).scalar() or 0

                summary["last_7d"] = conn.execute(text(
                    """
                    SELECT COUNT(*) FROM analyses
                    WHERE created_at >= NOW() - INTERVAL 7 DAY
                    """
                )).scalar() or 0
        except Exception as e:
            logger.error(f"Error building analysis summary: {e}")

        return summary

    def get_recent_analysis_results(self, limit: int = 15) -> List[Dict[str, Any]]:
        """Returns the most recent analysis result rows."""
        if not self.engine:
            return []

        limit = max(1, min(limit, 100))

        try:
            with self.engine.connect() as conn:
                if self._table_exists(conn, "analysis_results"):
                    query = text(
                        """
                        SELECT id, raw_text, ai_analysis, created_at
                        FROM analysis_results
                        ORDER BY created_at DESC
                        LIMIT :limit
                        """
                    )

                    records: List[Dict[str, Any]] = []
                    for row in conn.execute(query, {"limit": limit}).mappings():
                        ai_payload: Optional[Any] = row.get("ai_analysis")
                        if isinstance(ai_payload, str):
                            try:
                                ai_payload = json.loads(ai_payload)
                            except json.JSONDecodeError:
                                pass

                        records.append({
                            "id": row.get("id"),
                            "raw_text": row.get("raw_text"),
                            "ai_analysis": ai_payload,
                            "created_at": self._to_iso_datetime(row.get("created_at")),
                        })

                    return records

                if not self._table_exists(conn, "analyses"):
                    return []

                query = text(
                    """
                    SELECT
                        a.id,
                        a.scan_id,
                        a.summary,
                        a.recommendation,
                        a.status,
                        a.created_at,
                        s.extracted_text,
                        u.id AS user_id,
                        u.name AS user_name,
                        u.email AS user_email,
                        p.id AS product_id,
                        p.name AS product_name,
                        p.brand AS product_brand,
                        p.category AS product_category,
                        COUNT(DISTINCT si.ingredient_id) AS matched_ingredient_count,
                        GROUP_CONCAT(DISTINCT i.name ORDER BY i.name SEPARATOR ', ') AS matched_ingredients,
                        COUNT(DISTINCT ad.id) AS detail_count
                    FROM analyses a
                    LEFT JOIN scans s ON s.id = a.scan_id
                    LEFT JOIN users u ON u.id = s.user_id
                    LEFT JOIN products p ON p.id = s.product_id
                    LEFT JOIN scan_ingredients si ON si.scan_id = s.id
                    LEFT JOIN ingredients i ON i.id = si.ingredient_id
                    LEFT JOIN analysis_details ad ON ad.analysis_id = a.id
                    GROUP BY
                        a.id,
                        a.scan_id,
                        a.summary,
                        a.recommendation,
                        a.status,
                        a.created_at,
                        s.extracted_text,
                        u.id,
                        u.name,
                        u.email,
                        p.id,
                        p.name,
                        p.brand,
                        p.category
                    ORDER BY a.created_at DESC
                    LIMIT :limit
                    """
                )

                records: List[Dict[str, Any]] = []
                for row in conn.execute(query, {"limit": limit}).mappings():
                    raw_matched = row.get("matched_ingredients") or ""
                    matched_ingredients = [
                        item.strip() for item in str(raw_matched).split(",") if item and item.strip()
                    ]

                    ai_payload = {
                        "summary": row.get("summary"),
                        "recommendation": row.get("recommendation"),
                        "matched_ingredients": matched_ingredients,
                        "status": row.get("status"),
                    }

                    records.append({
                        "id": row.get("id"),
                        "scan_id": row.get("scan_id"),
                        "raw_text": row.get("extracted_text"),
                        "summary": row.get("summary"),
                        "recommendation": row.get("recommendation"),
                        "status": row.get("status"),
                        "matched_ingredient_count": row.get("matched_ingredient_count") or 0,
                        "matched_ingredients": matched_ingredients,
                        "detail_count": row.get("detail_count") or 0,
                        "user": {
                            "id": row.get("user_id"),
                            "name": row.get("user_name"),
                            "email": row.get("user_email"),
                        } if row.get("user_id") else None,
                        "product": {
                            "id": row.get("product_id"),
                            "name": row.get("product_name"),
                            "brand": row.get("product_brand"),
                            "category": row.get("product_category"),
                        } if row.get("product_id") else None,
                        "ai_analysis": ai_payload,
                        "created_at": self._to_iso_datetime(row.get("created_at")),
                    })

                return records
        except Exception as e:
            logger.error(f"Error fetching recent analysis results: {e}")
            return []

    def get_ingredient_summary(self) -> Dict[str, Any]:
        """Returns risk-oriented counts from the ingredients table for old/new schema."""
        summary = {
            "total": 0,
            "allergens": 0,
            "unsafe_for_pregnancy": 0,
            "high_comedogenic": 0,
            "average_comedogenic_rating": None,
            "last_updated_at": None,
            "low_risk": 0,
            "medium_risk": 0,
            "high_risk": 0,
            "unknown_risk": 0,
            "by_risk_level": {},
        }

        if not self.engine:
            return summary

        try:
            with self.engine.connect() as conn:
                if not self._table_exists(conn, "ingredients"):
                    return summary

                has_legacy_columns = (
                    self._column_exists(conn, "ingredients", "is_allergen")
                    and self._column_exists(conn, "ingredients", "unsafe_for_pregnancy")
                    and self._column_exists(conn, "ingredients", "comedogenic_rating")
                )

                if has_legacy_columns:
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
                        summary["last_updated_at"] = self._to_iso_datetime(stats.get("last_updated"))

                    return summary

                last_updated_column = "updated_at" if self._column_exists(conn, "ingredients", "updated_at") else "created_at"

                stats = conn.execute(text(
                    f"""
                    SELECT COUNT(*) AS total,
                           MAX({last_updated_column}) AS last_updated
                    FROM ingredients
                    """
                )).mappings().first()

                if stats:
                    summary["total"] = stats.get("total", 0) or 0
                    summary["last_updated_at"] = self._to_iso_datetime(stats.get("last_updated"))

                rows = conn.execute(text(
                    """
                    SELECT COALESCE(NULLIF(TRIM(risk_level), ''), 'unknown') AS risk_level,
                           COUNT(*) AS total
                    FROM ingredients
                    GROUP BY COALESCE(NULLIF(TRIM(risk_level), ''), 'unknown')
                    """
                )).mappings().all()

                distribution: Dict[str, int] = {
                    "low": 0,
                    "medium": 0,
                    "high": 0,
                    "unknown": 0,
                }

                for row in rows:
                    normalized = self._normalize_risk_level(row.get("risk_level"))
                    distribution[normalized] = distribution.get(normalized, 0) + (row.get("total", 0) or 0)

                summary["low_risk"] = distribution.get("low", 0)
                summary["medium_risk"] = distribution.get("medium", 0)
                summary["high_risk"] = distribution.get("high", 0)
                summary["unknown_risk"] = distribution.get("unknown", 0)
                summary["high_comedogenic"] = summary["high_risk"]
                summary["by_risk_level"] = distribution
        except Exception as e:
            logger.error(f"Error building ingredient summary: {e}")

        return summary

    def get_entity_summary(self) -> Dict[str, Any]:
        """Returns total rows for core tables used by the admin panel."""
        summary = {
            "users": 0,
            "products": 0,
            "ingredients": 0,
            "scans": 0,
            "analyses": 0,
            "analysis_details": 0,
            "scan_ingredients": 0,
            "user_histories": 0,
            "total_records": 0,
        }

        if not self.engine:
            return summary

        tracked_tables = [
            "users",
            "products",
            "ingredients",
            "scans",
            "analyses",
            "analysis_details",
            "scan_ingredients",
            "user_histories",
        ]

        try:
            with self.engine.connect() as conn:
                for table_name in tracked_tables:
                    if not self._table_exists(conn, table_name):
                        continue

                    count_value = conn.execute(text(f"SELECT COUNT(*) FROM {table_name}")).scalar()
                    summary[table_name] = count_value or 0

                summary["total_records"] = sum(summary[name] for name in tracked_tables)
        except Exception as e:
            logger.error(f"Error building entity summary: {e}")

        return summary

# Helper untuk mendapatkan instance dari koneksi database
def get_db_connection() -> DatabaseConnection:
    return DatabaseConnection()
