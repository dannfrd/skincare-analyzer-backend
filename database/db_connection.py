import os
import re
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

# Tambahkan fungsi get_db_session untuk FastAPI
from sqlalchemy.orm import sessionmaker

def get_db_session():
    engine = create_engine(DATABASE_URL, pool_recycle=3600)
    SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()

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

    def save_analysis_result(
        self,
        raw_text: str,
        ai_result: dict,
        matched_ingredients: Optional[List[Dict[str, Any]]] = None,
        expert_report: Optional[Dict[str, Any]] = None,
        user_id: Optional[int] = None,
        product_name: Optional[str] = None,
        product_brand: Optional[str] = None,
        product_category: Optional[str] = None,
        image_url: Optional[str] = None,
    ) -> Optional[int]:
        """
        Simpan satu hasil scan ke seluruh tabel relasional dalam satu transaksi.

        Urutan relasi:
        products -> scans -> scan_ingredients
                 -> analyses -> analysis_details

        user_histories sengaja tidak diisi di sini karena histori hanya dibuat
        ketika pengguna menekan tombol "Simpan Hasil".
        """
        if not self.engine:
            raise RuntimeError("Database connection is unavailable.")

        matched_ingredients = matched_ingredients or []
        expert_report = expert_report or {}

        try:
            with self.engine.begin() as conn:
                required_tables = {
                    "users",
                    "products",
                    "ingredients",
                    "scans",
                    "scan_ingredients",
                    "analyses",
                    "analysis_details",
                    "user_histories",
                }
                missing_tables = sorted(
                    table_name
                    for table_name in required_tables
                    if not self._table_exists(conn, table_name)
                )
                if missing_tables:
                    raise RuntimeError(
                        "Relational schema is incomplete. Missing tables: "
                        + ", ".join(missing_tables)
                    )

                resolved_user_id = user_id or self._ensure_system_user(conn)
                if not resolved_user_id:
                    raise RuntimeError("Unable to resolve the scan owner.")

                product_id = self._resolve_or_create_product(
                    conn,
                    product_name,
                    product_brand,
                    product_category,
                )

                scan_insert = conn.execute(text(
                    """
                    INSERT INTO scans (user_id, product_id, image_url, extracted_text, created_at)
                    VALUES (:user_id, :product_id, :image_url, :extracted_text, NOW())
                    """
                ), {
                    "user_id": resolved_user_id,
                    "product_id": product_id,
                    "image_url": image_url,
                    "extracted_text": raw_text,
                })
                scan_id = scan_insert.lastrowid

                self._resolve_ingredient_ids(conn, matched_ingredients)
                self._save_scan_ingredient_links(conn, scan_id, matched_ingredients)

                summary_text = self._extract_primary_text(
                    ai_result,
                    ["summary", "ringkasan", "result"],
                ) or self._build_summary_from_expert(expert_report)
                recommendation_text = self._extract_primary_text(
                    ai_result,
                    ["recommendation", "rekomendasi", "suggestion"],
                ) or self._build_recommendation_from_expert(expert_report)

                ai_analysis = ai_result.get("ai_analysis")
                if not isinstance(ai_analysis, dict):
                    ai_analysis = {}

                analysis_insert = conn.execute(text(
                    """
                    INSERT INTO analyses (
                        scan_id,
                        summary,
                        recommendation,
                        status,
                        overall_score,
                        classification,
                        warnings_count,
                        unknown_count,
                        ai_model,
                        ai_output,
                        raw_result,
                        created_at
                    )
                    VALUES (
                        :scan_id,
                        :summary,
                        :recommendation,
                        :status,
                        :overall_score,
                        :classification,
                        :warnings_count,
                        :unknown_count,
                        :ai_model,
                        :ai_output,
                        :raw_result,
                        NOW()
                    )
                    """
                ), {
                    "scan_id": scan_id,
                    "summary": summary_text,
                    "recommendation": recommendation_text,
                    "status": "completed",
                    "overall_score": expert_report.get("overall_score"),
                    "classification": expert_report.get("classification"),
                    "warnings_count": expert_report.get("warnings_found") or 0,
                    "unknown_count": expert_report.get("total_unknown") or 0,
                    "ai_model": ai_analysis.get("model_used") or ai_analysis.get("model"),
                    "ai_output": (
                        ai_analysis.get("model_output")
                        or ai_analysis.get("text")
                        or recommendation_text
                    ),
                    # Store full JSON result payload when available
                    "raw_result": json.dumps(ai_result, ensure_ascii=False, default=str) if ai_result is not None else None,
                })
                analysis_id = analysis_insert.lastrowid

                self._save_analysis_details(
                    conn,
                    analysis_id,
                    matched_ingredients,
                    expert_report,
                )
                return analysis_id
        except Exception as e:
            logger.error(f"Error saving analysis result: {e}")
            raise RuntimeError("Failed to persist relational analysis data.") from e

    def _resolve_ingredient_ids(self, conn, matched_ingredients: List[Dict[str, Any]]) -> None:
        """
        Resolve known ingredients and insert dataset-backed ingredients.

        Unknown OCR text without an exact dataset match stays in the analysis
        payload but is not promoted into the master ingredients table.
        """
        if not self._table_exists(conn, "ingredients"):
            return

        for ingredient in matched_ingredients:
            # Already resolved
            if isinstance(ingredient.get("id"), int):
                continue

            # Determine canonical name
            name = str(
                ingredient.get("name") or ingredient.get("ocr_token_used") or ""
            ).strip().upper()
            import re as _re
            name = _re.sub(r'^[^A-Z0-9]+|[^A-Z0-9\s\-\(\)]+$', '', name).strip()

            if not name or len(name) < 2:
                continue

            # 1. Try to find existing row
            existing = conn.execute(
                text(
                    """
                    SELECT id, description, `function`
                    FROM ingredients
                    WHERE name = :name
                    LIMIT 1
                    """
                ),
                {"name": name},
            ).mappings().first()

            if existing:
                ingredient["id"] = existing.get("id")

                dataset_description = str(
                    ingredient.get("dataset_description") or ""
                ).strip()
                dataset_functions = str(
                    ingredient.get("dataset_functions") or ""
                ).strip()
                current_description = str(existing.get("description") or "").strip()
                current_function = str(existing.get("function") or "").strip()

                updates = {}
                if dataset_description and (
                    not current_description
                    or current_description.lower()
                    in {"unknown", "ingredient not found in database."}
                ):
                    updates["description"] = dataset_description

                if dataset_functions and (
                    not current_function or current_function.lower() == "unknown"
                ):
                    updates["function"] = dataset_functions

                if updates:
                    conn.execute(
                        text(
                            """
                            UPDATE ingredients
                            SET description = COALESCE(:description, description),
                                `function` = COALESCE(:function, `function`)
                            WHERE id = :id
                            """
                        ),
                        {
                            "id": ingredient["id"],
                            "description": updates.get("description"),
                            "function": updates.get("function"),
                        },
                    )

                logger.debug(f"Resolved existing ingredient: {name} -> id={ingredient['id']}")
                continue

            status = str(ingredient.get("status") or "").strip().lower()
            if status == "unknown" and not ingredient.get("found_in_dataset"):
                logger.info("Skipped unknown OCR token from master data: %s", name)
                continue

            # 2. Auto-insert ingredients backed by DB matching or the dataset.
            desc_val = str(
                ingredient.get("dataset_description") or ingredient.get("description") or ""
            ).strip()
            desc = desc_val if desc_val and desc_val.lower() != "unknown" else "Bahan kosmetik / perawatan kulit umum."

            func_val = str(
                ingredient.get("dataset_functions") or ingredient.get("function") or ""
            ).strip()
            func = func_val if func_val and func_val.lower() != "unknown" else "General Skincare Ingredient"

            # Determine risk level
            if ingredient.get("dataset_harmful"):
                risk_level = "high"
            elif status == "unknown":
                risk_level = "unknown"
            else:
                risk_level = "low"

            try:
                insert = conn.execute(
                    text(
                        """
                        INSERT INTO ingredients (name, description, `function`, risk_level, created_at)
                        VALUES (:name, :desc, :func, :risk, NOW())
                        """
                    ),
                    {
                        "name": name,
                        "desc": desc,
                        "func": func,
                        "risk": risk_level,
                    },
                )
                ingredient["id"] = insert.lastrowid
                logger.info(f"Auto-inserted ingredient: {name} (risk={risk_level}) -> id={ingredient['id']}")
            except Exception as e:
                # Most likely a duplicate race condition - try fetching again
                logger.warning(f"Insert failed for {name}, retrying fetch: {e}")
                retry = conn.execute(
                    text("SELECT id FROM ingredients WHERE name = :name LIMIT 1"),
                    {"name": name},
                ).fetchone()
                if retry:
                    ingredient["id"] = retry.id if hasattr(retry, "id") else retry[0]


    def _extract_primary_text(self, payload: Dict[str, Any], keys: List[str]) -> str:
        for key in keys:
            value = payload.get(key)
            if isinstance(value, str) and value.strip():
                return value.strip()
        return ""

    def _build_summary_from_expert(self, expert_report: Dict[str, Any]) -> str:
        if not isinstance(expert_report, dict):
            return ""

        score = expert_report.get("overall_score")
        classification = expert_report.get("classification")
        total_identified = expert_report.get("total_ingredients_identified")
        warning_count = expert_report.get("warnings_found")

        return (
            f"Skor keamanan {score}/100 ({classification}). "
            f"Bahan dikenali: {total_identified}. "
            f"Peringatan: {warning_count}."
        )

    def _build_recommendation_from_expert(self, expert_report: Dict[str, Any]) -> str:
        if not isinstance(expert_report, dict):
            return ""

        flags = expert_report.get("flags") or []
        if isinstance(flags, list) and flags:
            first_flag = flags[0] if isinstance(flags[0], dict) else {}
            ingredient = first_flag.get("ingredient")
            message = first_flag.get("message")
            if ingredient and message:
                return f"Perhatikan ingredient {ingredient}: {message}"

        unknown_count = expert_report.get("total_unknown", 0)
        if isinstance(unknown_count, int) and unknown_count > 0:
            return (
                f"Ada {unknown_count} bahan yang belum dikenali. "
                "Lengkapi master ingredients agar analisis lebih akurat."
            )

        return "Secara umum formula cukup aman, tetap lakukan patch test sebelum pemakaian rutin."

    def _save_scan_ingredient_links(
        self,
        conn,
        scan_id: int,
        matched_ingredients: List[Dict[str, Any]],
    ) -> None:
        if not self._table_exists(conn, "scan_ingredients"):
            return

        linked_ingredient_ids = set()
        for position_index, ingredient in enumerate(matched_ingredients):
            ingredient_id = ingredient.get("id")
            if not isinstance(ingredient_id, int) or ingredient_id in linked_ingredient_ids:
                continue

            linked_ingredient_ids.add(ingredient_id)
            status = str(ingredient.get("status") or "").strip().lower()
            match_status = "unknown" if status == "unknown" else "matched"
            confidence = ingredient.get("match_confidence")
            if confidence is None and match_status == "matched":
                confidence = 1.0

            conn.execute(text(
                """
                INSERT INTO scan_ingredients (
                    scan_id,
                    ingredient_id,
                    position_index,
                    ocr_token,
                    match_status,
                    match_confidence
                )
                VALUES (
                    :scan_id,
                    :ingredient_id,
                    :position_index,
                    :ocr_token,
                    :match_status,
                    :match_confidence
                )
                ON DUPLICATE KEY UPDATE
                    position_index = VALUES(position_index),
                    ocr_token = VALUES(ocr_token),
                    match_status = VALUES(match_status),
                    match_confidence = VALUES(match_confidence)
                """
            ), {
                "scan_id": scan_id,
                "ingredient_id": ingredient_id,
                "position_index": position_index,
                "ocr_token": ingredient.get("ocr_token_used") or ingredient.get("name"),
                "match_status": match_status,
                "match_confidence": confidence,
            })

    def _save_analysis_details(
        self,
        conn,
        analysis_id: int,
        matched_ingredients: List[Dict[str, Any]],
        expert_report: Dict[str, Any],
    ) -> None:
        if not self._table_exists(conn, "analysis_details"):
            return

        warning_map = self._build_warning_map(expert_report.get("flags"))

        saved_ingredient_ids = set()
        for ingredient in matched_ingredients:
            ingredient_id = ingredient.get("id")
            if (
                not isinstance(ingredient_id, int)
                or ingredient_id in saved_ingredient_ids
            ):
                continue
            saved_ingredient_ids.add(ingredient_id)

            ingredient_name = str(ingredient.get("name") or "").upper()
            
            # Menggunakan data dari Qdrant (RAG) jika tersedia
            dataset_functions = str(ingredient.get("dataset_functions") or "").strip()
            raw_func = dataset_functions if dataset_functions else str(ingredient.get("function") or "")
            function_text = raw_func.strip() if raw_func.strip() and raw_func.strip().lower() != "unknown" else "General Skincare Ingredient"
            
            dataset_description = str(ingredient.get("dataset_description") or "").strip()
            raw_benefit = dataset_description if dataset_description else str(ingredient.get("description") or "")
            benefit_text = raw_benefit.strip() if raw_benefit.strip() and raw_benefit.strip().lower() != "unknown" else "Komponen formula perawatan kulit untuk menjaga tekstur dan efektivitas produk."

            risk_parts: List[str] = []
            
            # Harmful BPOM Check
            if ingredient.get("dataset_harmful"):
                risk_parts.append("BPOM BANNED/HARMFUL")
                
            dataset_bpom_warning = str(ingredient.get("dataset_bpom_warning") or "").strip()
            if dataset_bpom_warning:
                risk_parts.append(dataset_bpom_warning)
                
            dataset_warnings = str(ingredient.get("dataset_warnings") or "").strip()
            if dataset_warnings:
                risk_parts.append(f"Warning: {dataset_warnings}")

            risk_level = str(ingredient.get("risk_level") or "").strip()
            if risk_level:
                risk_parts.append(f"Risk level: {risk_level}")

            warning_text = warning_map.get(ingredient_name)
            if warning_text:
                risk_parts.append(f"AI Warning: {warning_text}")

            risk_text = " | ".join(risk_parts) if risk_parts else "No specific risk flagged"

            conn.execute(text(
                """
                INSERT INTO analysis_details (analysis_id, ingredient_id, `function`, benefit, risk)
                VALUES (:analysis_id, :ingredient_id, :function, :benefit, :risk)
                """
            ), {
                "analysis_id": analysis_id,
                "ingredient_id": ingredient_id,
                "function": function_text,
                "benefit": benefit_text,
                "risk": risk_text,
            })

    def _build_warning_map(self, flags: Any) -> Dict[str, str]:
        warning_map: Dict[str, str] = {}

        if not isinstance(flags, list):
            return warning_map

        for flag in flags:
            if not isinstance(flag, dict):
                continue

            ingredient = str(flag.get("ingredient") or "").strip().upper()
            message = str(flag.get("message") or "").strip()
            if not ingredient or not message:
                continue

            if ingredient in warning_map:
                warning_map[ingredient] = f"{warning_map[ingredient]}; {message}"
            else:
                warning_map[ingredient] = message

        return warning_map

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
            FROM DUAL
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

    def _resolve_or_create_product(
        self,
        conn,
        name: Optional[str],
        brand: Optional[str],
        category: Optional[str],
    ) -> Optional[int]:
        normalized_name = (name or "").strip()
        normalized_brand = (brand or "").strip()
        normalized_category = (category or "").strip()

        if not (normalized_name or normalized_brand or normalized_category):
            return None

        name_value = normalized_name or None
        brand_value = normalized_brand or None
        category_value = normalized_category or None

        existing = conn.execute(text(
            """
            SELECT id
            FROM products
            WHERE name <=> :name AND brand <=> :brand
            LIMIT 1
            """
        ), {
            "name": name_value,
            "brand": brand_value,
        }).fetchone()

        if existing:
            product_id = existing.id if hasattr(existing, "id") else existing[0]
            conn.execute(text(
                """
                UPDATE products
                SET category = COALESCE(NULLIF(:category, ''), category)
                WHERE id = :product_id
                """
            ), {
                "category": category_value,
                "product_id": product_id,
            })
            return product_id

        insert = conn.execute(text(
            """
            INSERT INTO products (name, brand, category, created_at)
            VALUES (:name, :brand, :category, NOW())
            """
        ), {
            "name": name_value,
            "brand": brand_value,
            "category": category_value,
        })

        return insert.lastrowid

    # --- Notifications CRUD helpers ---
    def create_notification(self, title: str, body: Optional[str], data: Optional[Dict[str, Any]], topic: Optional[str], tokens: Optional[list], status: str = "draft", scheduled_at: Optional[str] = None, sent_by: Optional[int] = None) -> Optional[int]:
        if not self.engine:
            return None
        try:
            # Normalize flexible input types: frontend may send JSON as strings
            data_val = None
            if data is not None:
                if isinstance(data, str):
                    try:
                        # try parse JSON string
                        data_parsed = json.loads(data)
                        data_val = json.dumps(data_parsed, ensure_ascii=False)
                    except Exception:
                        # store raw string
                        data_val = data
                else:
                    data_val = json.dumps(data, ensure_ascii=False)

            tokens_val = None
            if tokens is not None:
                if isinstance(tokens, str):
                    try:
                        tokens_parsed = json.loads(tokens)
                        tokens_val = json.dumps(tokens_parsed, ensure_ascii=False)
                    except Exception:
                        tokens_val = tokens
                else:
                    tokens_val = json.dumps(tokens, ensure_ascii=False)

            sched_val = None
            if scheduled_at:
                # Accept ISO strings, with or without trailing Z
                if isinstance(scheduled_at, str):
                    try:
                        s = scheduled_at.rstrip("Z")
                        # fromisoformat can parse YYYY-MM-DDTHH:MM:SS[.ffffff]
                        sched_dt = datetime.fromisoformat(s)
                        sched_val = sched_dt
                    except Exception:
                        # pass through as string for DB to attempt cast
                        sched_val = scheduled_at
                elif isinstance(scheduled_at, datetime):
                    sched_val = scheduled_at

            with self.engine.begin() as conn:
                insert = conn.execute(text(
                    "INSERT INTO notifications (title, body, data, topic, tokens, status, scheduled_at, sent_by, created_at) VALUES (:title, :body, :data, :topic, :tokens, :status, :scheduled_at, :sent_by, NOW())"
                ), {
                    "title": title,
                    "body": body,
                    "data": data_val,
                    "topic": topic,
                    "tokens": tokens_val,
                    "status": status,
                    "scheduled_at": sched_val,
                    "sent_by": sent_by,
                })
                try:
                    return insert.lastrowid
                except Exception:
                    # Some DB drivers return inserted_primary_key differently
                    res = insert
                    try:
                        return int(res.inserted_primary_key[0])
                    except Exception:
                        return None
        except Exception as e:
            logger.exception(f"Error creating notification: {e}")
            return None

    def get_notifications(self, limit: int = 50, offset: int = 0) -> List[Dict[str, Any]]:
        if not self.engine:
            return []
        try:
            with self.engine.connect() as conn:
                if not self._table_exists(conn, "notifications"):
                    return []
                query = text(
                    "SELECT id, title, body, data, topic, tokens, status, scheduled_at, sent_at, sent_by, created_at FROM notifications ORDER BY created_at DESC LIMIT :limit OFFSET :offset"
                )
                rows = conn.execute(query, {"limit": limit, "offset": offset}).mappings().all()
                results: List[Dict[str, Any]] = []
                for row in rows:
                    data_val = row.get("data")
                    if isinstance(data_val, str):
                        try:
                            data_val = json.loads(data_val)
                        except Exception:
                            pass

                    tokens_val = row.get("tokens")
                    if isinstance(tokens_val, str):
                        try:
                            tokens_val = json.loads(tokens_val)
                        except Exception:
                            pass
                    target_user_id = None
                    if isinstance(data_val, dict):
                        target_user_id = data_val.get("target_user_id") or data_val.get("user_id")

                    results.append({
                        "id": row.get("id"),
                        "title": row.get("title"),
                        "body": row.get("body"),
                        "data": data_val,
                        "topic": row.get("topic"),
                        "tokens": tokens_val,
                        "user_id": target_user_id,
                        "target_user_id": target_user_id,
                        "status": row.get("status"),
                        "scheduled_at": self._to_iso_datetime(row.get("scheduled_at")),
                        "sent_at": self._to_iso_datetime(row.get("sent_at")),
                        "sent_by": row.get("sent_by"),
                        "created_at": self._to_iso_datetime(row.get("created_at")),
                    })
                return results
        except Exception as e:
            logger.error(f"Error fetching notifications: {e}")
            return []

    def get_notification_by_id(self, notification_id: int) -> Optional[Dict[str, Any]]:
        if not self.engine:
            return None
        try:
            with self.engine.connect() as conn:
                if not self._table_exists(conn, "notifications"):
                    return None
                row = conn.execute(text(
                    "SELECT id, title, body, data, topic, tokens, status, scheduled_at, sent_at, sent_by, created_at FROM notifications WHERE id = :id LIMIT 1"
                ), {"id": notification_id}).mappings().first()
                if not row:
                    return None

                data_val = row.get("data")
                if isinstance(data_val, str):
                    try:
                        data_val = json.loads(data_val)
                    except Exception:
                        pass

                tokens_val = row.get("tokens")
                if isinstance(tokens_val, str):
                    try:
                        tokens_val = json.loads(tokens_val)
                    except Exception:
                        pass
                target_user_id = None
                if isinstance(data_val, dict):
                    target_user_id = data_val.get("target_user_id") or data_val.get("user_id")

                return {
                    "id": row.get("id"),
                    "title": row.get("title"),
                    "body": row.get("body"),
                    "data": data_val,
                    "topic": row.get("topic"),
                    "tokens": tokens_val,
                    "user_id": target_user_id,
                    "target_user_id": target_user_id,
                    "status": row.get("status"),
                    "scheduled_at": self._to_iso_datetime(row.get("scheduled_at")),
                    "sent_at": self._to_iso_datetime(row.get("sent_at")),
                    "sent_by": row.get("sent_by"),
                    "created_at": self._to_iso_datetime(row.get("created_at")),
                }
        except Exception as e:
            logger.error(f"Error fetching notification by id: {e}")
            return None

    def mark_notification_sent(self, notification_id: int, sent_by: Optional[int] = None) -> bool:
        if not self.engine:
            return False
        try:
            with self.engine.begin() as conn:
                conn.execute(text(
                    "UPDATE notifications SET status = 'sent', sent_at = NOW(), sent_by = :sent_by WHERE id = :id"
                ), {"id": notification_id, "sent_by": sent_by})
                return True
        except Exception as e:
            logger.error(f"Error marking notification sent: {e}")
            return False

    def mark_notification_failed(self, notification_id: int) -> bool:
        if not self.engine:
            return False
        try:
            with self.engine.begin() as conn:
                conn.execute(text(
                    "UPDATE notifications SET status = 'failed' WHERE id = :id"
                ), {"id": notification_id})
                return True
        except Exception as e:
            logger.error(f"Error marking notification failed: {e}")
            return False

    def update_notification(self, notification_id: int, title: str, body: Optional[str], data: Optional[Dict[str, Any]], topic: Optional[str], tokens: Optional[list], status: str, scheduled_at: Optional[str] = None) -> bool:
        if not self.engine:
            return False
        try:
            data_val = None
            if data is not None:
                if isinstance(data, str):
                    try:
                        data_parsed = json.loads(data)
                        data_val = json.dumps(data_parsed, ensure_ascii=False)
                    except Exception:
                        data_val = data
                else:
                    data_val = json.dumps(data, ensure_ascii=False)

            tokens_val = None
            if tokens is not None:
                if isinstance(tokens, str):
                    try:
                        tokens_parsed = json.loads(tokens)
                        tokens_val = json.dumps(tokens_parsed, ensure_ascii=False)
                    except Exception:
                        tokens_val = tokens
                else:
                    tokens_val = json.dumps(tokens, ensure_ascii=False)

            sched_val = None
            if scheduled_at:
                if isinstance(scheduled_at, str):
                    try:
                        s = scheduled_at.rstrip("Z")
                        sched_dt = datetime.fromisoformat(s)
                        sched_val = sched_dt
                    except Exception:
                        sched_val = scheduled_at
                elif isinstance(scheduled_at, datetime):
                    sched_val = scheduled_at

            with self.engine.begin() as conn:
                conn.execute(text(
                    """
                    UPDATE notifications
                    SET title = :title,
                        body = :body,
                        data = :data,
                        topic = :topic,
                        tokens = :tokens,
                        status = :status,
                        scheduled_at = :scheduled_at
                    WHERE id = :id
                    """
                ), {
                    "id": notification_id,
                    "title": title,
                    "body": body,
                    "data": data_val,
                    "topic": topic,
                    "tokens": tokens_val,
                    "status": status,
                    "scheduled_at": sched_val
                })
                return True
        except Exception as e:
            logger.error(f"Error updating notification: {e}")
            return False

    def delete_notification(self, notification_id: int) -> bool:
        if not self.engine:
            return False
        try:
            with self.engine.begin() as conn:
                conn.execute(text("DELETE FROM notifications WHERE id = :id"), {"id": notification_id})
                return True
        except Exception as e:
            logger.error(f"Error deleting notification: {e}")
            return False

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
                if self._table_exists(conn, "analyses"):
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

                    return summary

                if not self._table_exists(conn, "analysis_results"):
                    return summary

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
                if self._table_exists(conn, "analyses"):
                    query = text(
                        """
                        SELECT
                            a.id,
                            a.scan_id,
                            a.summary,
                            a.recommendation,
                            a.status,
                            a.overall_score,
                            a.classification,
                            a.warnings_count,
                            a.unknown_count,
                            a.ai_model,
                            a.ai_output,
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
                            a.overall_score,
    def get_recent_analysis_results(self, limit: int = 15) -> List[Dict[str, Any]]:
        """Returns the most recent analysis result rows."""
        if not self.engine:
            return []

        limit = max(1, min(limit, 100))

        try:
            with self.engine.connect() as conn:
                if self._table_exists(conn, "analyses"):
                    query = text(
                        """
                        SELECT
                            a.id,
                            a.scan_id,
                            a.summary,
                            a.recommendation,
                            a.status,
                            a.overall_score,
                            a.classification,
                            a.warnings_count,
                            a.unknown_count,
                            a.ai_model,
                            a.ai_output,
                            a.created_at,
                            s.extracted_text,
                            s.image_url,
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
                            a.overall_score,
                            a.classification,
                            a.warnings_count,
                            a.unknown_count,
                            a.ai_model,
                            a.ai_output,
                            a.created_at,
                            s.extracted_text,
                            s.image_url,
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
                            "model_output": row.get("ai_output"),
                            "model_used": row.get("ai_model"),
                            "models_tried": [],
                        }

                        records.append({
                            "id": row.get("id"),
                            "scan_id": row.get("scan_id"),
                            "raw_text": row.get("extracted_text"),
                            "image_url": row.get("image_url"),
                            "summary": row.get("summary"),
                            "recommendation": row.get("recommendation"),
                            "status": row.get("status"),
                            "overall_score": row.get("overall_score"),
                            "classification": row.get("classification"),
                            "warnings_count": row.get("warnings_count") or 0,
                            "unknown_count": row.get("unknown_count") or 0,
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

                if not self._table_exists(conn, "analysis_results"):
                    return []

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
        except Exception as e:
            logger.error(f"Error fetching recent analysis results: {e}")
            return []

    def get_analysis_detail(self, analysis_id: int) -> Optional[Dict[str, Any]]:
        """Returns a single analysis detail payload for app consumption."""
        if not self.engine:
            return None

        try:
            with self.engine.connect() as conn:
                if self._table_exists(conn, "analyses"):
                    # Build SELECT dynamically based on which columns exist in `analyses` to
                    # avoid querying missing legacy columns (prevents OperationalError).
                    cols = [
                        "a.id",
                        "a.scan_id",
                        "a.summary",
                        "a.recommendation",
                    ]

                    optional_cols = [
                        "expert_analysis",
                        "ai_analysis",
                        "raw_result",
                        "status",
                        "overall_score",
                        "classification",
                        "warnings_count",
                        "unknown_count",
                        "ai_model",
                        "ai_output",
                        "created_at",
                    ]

                    for c in optional_cols:
                        if self._column_exists(conn, "analyses", c):
                            cols.append(f"a.{c}")

                    # Always include joined context columns
                    cols.extend([
                        "s.extracted_text",
                        "s.image_url",
                        "u.id AS user_id",
                        "u.name AS user_name",
                        "u.email AS user_email",
                        "p.id AS product_id",
                        "p.name AS product_name",
                        "p.brand AS product_brand",
                        "p.category AS product_category",
                    ])

                    join_str = ',\n    '.join(cols)
                    sql = (
                        "SELECT\n    " + join_str +
                        "\nFROM analyses a\nLEFT JOIN scans s ON s.id = a.scan_id\nLEFT JOIN users u ON u.id = s.user_id\nLEFT JOIN products p ON p.id = s.product_id\nWHERE a.id = :analysis_id\nLIMIT 1"
                    )

                    base_row = conn.execute(text(sql), {"analysis_id": analysis_id}).mappings().first()

                    if not base_row:
                        # Fallback: if legacy `analysis_results` table exists, try fetching from there
                        if self._table_exists(conn, "analysis_results"):
                            row = conn.execute(text(
                                """
                                SELECT id, raw_text, ai_analysis, created_at
                                FROM analysis_results
                                WHERE id = :analysis_id
                                LIMIT 1
                                """
                            ), {"analysis_id": analysis_id}).mappings().first()

                            if not row:
                                return None

                            ai_payload: Any = row.get("ai_analysis")
                            if isinstance(ai_payload, str):
                                try:
                                    ai_payload = json.loads(ai_payload)
                                except json.JSONDecodeError:
                                    pass

                            return {
                                "id": row.get("id"),
                                "raw_text": row.get("raw_text"),
                                "ai_analysis": ai_payload,
                                "created_at": self._to_iso_datetime(row.get("created_at")),
                            }
                        return None

                    # If a raw_result payload was stored, prefer returning it verbatim
                    raw_payload = base_row.get("raw_result")
                    if isinstance(raw_payload, str) and raw_payload.strip():
                        try:
                            parsed = json.loads(raw_payload)
                        except Exception:
                            parsed = raw_payload

                        if isinstance(parsed, dict):
                            # Ensure identifiers and timestamps are present for clients
                            parsed.setdefault("analysis_id", base_row.get("id"))
                            parsed.setdefault("id", base_row.get("id"))
                            parsed.setdefault("created_at", self._to_iso_datetime(base_row.get("created_at")))
                            return parsed

                    ingredient_rows = conn.execute(text(
                        """
                        SELECT
                            i.id,
                            i.name,
                            i.risk_level,
                            i.description,
                            i.`function` AS ingredient_function,
                            si.position_index,
                            si.ocr_token,
                            si.match_status,
                            si.match_confidence,
                            ad.`function` AS analysis_function,
                            ad.benefit,
                            ad.risk
                        FROM analyses a
                        LEFT JOIN scans s ON s.id = a.scan_id
                        LEFT JOIN scan_ingredients si ON si.scan_id = s.id
                        LEFT JOIN ingredients i ON i.id = si.ingredient_id
                        LEFT JOIN analysis_details ad
                            ON ad.analysis_id = a.id
                           AND ad.ingredient_id = i.id
                        WHERE a.id = :analysis_id
                        ORDER BY si.position_index ASC, i.name ASC
                        """
                    ), {"analysis_id": analysis_id}).mappings().all()

                    matched_ingredients: List[Dict[str, Any]] = []
                    for row in ingredient_rows:
                        ingredient_id = row.get("id")
                        if not ingredient_id:
                            continue

                        matched_ingredients.append({
                            "id": ingredient_id,
                            "name": row.get("name"),
                            "risk_level": row.get("risk_level"),
                            "function": row.get("analysis_function") or row.get("ingredient_function"),
                            "description": row.get("description"),
                            "benefit": row.get("benefit"),
                            "risk": row.get("risk"),
                            "dataset_description": row.get("benefit") or row.get("description"),
                            "dataset_functions": row.get("analysis_function") or row.get("ingredient_function"),
                            "dataset_warnings": (
                                row.get("risk")
                                if row.get("risk") != "No specific risk flagged"
                                else None
                            ),
                            "ocr_token_used": row.get("ocr_token"),
                            "status": (
                                "Unknown"
                                if row.get("match_status") == "unknown"
                                else "Matched"
                            ),
                            "match_confidence": row.get("match_confidence"),
                            "found_in_dataset": row.get("match_status") != "unknown",
                        })

                    unknown_list = [
                        ingredient.get("name")
                        for ingredient in matched_ingredients
                        if ingredient.get("status") == "Unknown"
                    ]
                    flags = [
                        {
                            "ingredient": ingredient.get("name"),
                            "message": ingredient.get("risk"),
                        }
                        for ingredient in matched_ingredients
                        if ingredient.get("risk")
                        and ingredient.get("risk") != "No specific risk flagged"
                    ]
                    warnings_count = base_row.get("warnings_count") or 0

                    # Parse JSON text back to Dict
                    expert_payload = base_row.get("expert_analysis")
                    if isinstance(expert_payload, str):
                        try:
                            expert_payload = json.loads(expert_payload)
                        except json.JSONDecodeError:
                            pass

                    ai_payload = base_row.get("ai_analysis")
                    if isinstance(ai_payload, str):
                        try:
                            ai_payload = json.loads(ai_payload)
                        except json.JSONDecodeError:
                            pass

                    return {
                        "id": base_row.get("id"),
                        "scan_id": base_row.get("scan_id"),
                        "raw_text": base_row.get("extracted_text"),
                        "image_url": base_row.get("image_url"),
                        "summary": base_row.get("summary"),
                        "recommendation": base_row.get("recommendation"),
                        "status": base_row.get("status"),
                        "expert_analysis": expert_payload,   # Kirim kembali ke Flutter
                        "ai_analysis": ai_payload,           # Kirim kembali ke Flutter
                        "matched_ingredient_count": len(matched_ingredients),
                        "matched_ingredients": matched_ingredients,
                        "expert_analysis": {
                            "overall_score": base_row.get("overall_score"),
                            "classification": base_row.get("classification"),
                            "warnings_found": warnings_count or len(flags),
                            "total_ingredients_identified": (
                                len(matched_ingredients) - len(unknown_list)
                            ),
                            "total_unknown": base_row.get("unknown_count") or len(unknown_list),
                            "flags": flags,
                            "unknown_list": unknown_list,
                        },
                        "ai_analysis": {
                            "model_output": base_row.get("ai_output"),
                            "model_used": base_row.get("ai_model"),
                            "models_tried": [],
                        },
                        "user": {
                            "id": base_row.get("user_id"),
                            "name": base_row.get("user_name"),
                            "email": base_row.get("user_email"),
                        } if base_row.get("user_id") else None,
                        "product": {
                            "id": base_row.get("product_id"),
                            "name": base_row.get("product_name"),
                            "brand": base_row.get("product_brand"),
                            "category": base_row.get("product_category"),
                        } if base_row.get("product_id") else None,
                        "created_at": self._to_iso_datetime(base_row.get("created_at")),
                    }

                if not self._table_exists(conn, "analysis_results"):
                    return None

                row = conn.execute(text(
                    """
                    SELECT id, raw_text, ai_analysis, created_at
                    FROM analysis_results
                    WHERE id = :analysis_id
                    LIMIT 1
                    """
                ), {"analysis_id": analysis_id}).mappings().first()

                if not row:
                    return None

                ai_payload: Any = row.get("ai_analysis")
                if isinstance(ai_payload, str):
                    try:
                        ai_payload = json.loads(ai_payload)
                    except json.JSONDecodeError:
                        pass

                return {
                    "id": row.get("id"),
                    "raw_text": row.get("raw_text"),
                    "ai_analysis": ai_payload,
                    "created_at": self._to_iso_datetime(row.get("created_at")),
                }
        except Exception as e:
            logger.error(f"Error fetching analysis detail for ID {analysis_id}: {e}")
            return None

    def get_analyses(self, limit: int = 200) -> List[Dict[str, Any]]:
        """Returns a list of analyses with related user and product context."""
        if not self.engine:
            return []
                )

                rows = conn.execute(query, {"limit": limit}).mappings().all()

                result = []
                for row in rows:
                    raw_matched = row.get("matched_ingredients")
                    matched_list = [item.strip() for item in str(raw_matched).split(",") if item.strip()] if raw_matched else []
                    result.append({
                        "id": row.get("id"),
                        "user_id": row.get("user_id"),
                        "user_name": row.get("user_name"),
                        "user_email": row.get("user_email"),
                        "analysis_id": row.get("analysis_id"),
                        "analysis_status": row.get("analysis_status"),
                        "product_name": row.get("product_name"),
                        "product_brand": row.get("product_brand"),
                        "product_category": row.get("product_category"),
                        "summary": row.get("analysis_summary"),
                        "recommendation": row.get("analysis_recommendation"),
                        "extracted_text": row.get("extracted_text"),
                        "matched_ingredient_count": row.get("matched_ingredient_count") or 0,
                        "matched_ingredients": matched_list,
                        "analysis_created_at": self._to_iso_datetime(row.get("analysis_created_at")),
                        "viewed_at": self._to_iso_datetime(row.get("viewed_at")),
                    })
                return result
        except Exception as e:
            logger.error(f"Error fetching user histories list: {e}")
            return []

    def set_reset_otp(self, email: str, otp: str, expires_at: datetime) -> bool:
        if not self.engine:
            return False
        try:
            with self.engine.begin() as conn:
                result = conn.execute(
                    text("UPDATE users SET reset_otp = :otp, reset_otp_expires_at = :expires_at WHERE email = :email"),
                    {"otp": otp, "expires_at": expires_at, "email": email}
                )
                return result.rowcount > 0
        except Exception as e:
            logger.error(f"Error setting reset OTP: {e}")
            return False

    def verify_and_clear_reset_otp(self, email: str, otp: str) -> bool:
        if not self.engine:
            return False
        try:
            with self.engine.begin() as conn:
                row = conn.execute(
                    text("SELECT reset_otp, reset_otp_expires_at FROM users WHERE email = :email LIMIT 1"),
                    {"email": email}
                ).mappings().first()

                if not row or row.get("reset_otp") != otp:
                    return False
                
                expires_at = row.get("reset_otp_expires_at")
                if not expires_at or expires_at < datetime.now():
                    return False

                # Valid, so clear it
                conn.execute(
                    text("UPDATE users SET reset_otp = NULL, reset_otp_expires_at = NULL WHERE email = :email"),
                    {"email": email}
                )
                return True
        except Exception as e:
            logger.error(f"Error verifying reset OTP: {e}")
            return False

# Helper untuk mendapatkan instance dari koneksi database
def get_db_connection() -> DatabaseConnection:
    return DatabaseConnection()
