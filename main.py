import os
os.environ.setdefault("HF_HUB_DISABLE_TELEMETRY", "1")
os.environ.setdefault("HF_HUB_DISABLE_SYMLINKS_WARNING", "1")
# Fix internal PaddlePaddle CPU bugs by disabling PIR and MKLDNN globally
os.environ['FLAGS_enable_pir_api'] = '0'
os.environ['FLAGS_use_mkldnn'] = '0'

from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from fastapi import Depends, FastAPI, File, Form, Header, HTTPException, Query, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi import Request
from fastapi.staticfiles import StaticFiles
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, EmailStr, Field
import shutil
import os
import time
import json
from jose import jwt, JWTError
from dotenv import load_dotenv
from apscheduler.schedulers.background import BackgroundScheduler

load_dotenv()

SECRET_KEY = os.getenv("SECRET_KEY", "secret")
ALGORITHM = "HS256"

from modules.text_cleaning import clean_text_pipeline, extract_ingredient_text
from modules.ingredient_matching import match_tokens_to_db
from modules.gemini_ai import analyze_ingredients_with_ai, generate_simple_descriptions
import concurrent.futures
from modules.expert_system import run_expert_system
from modules.rag_context import get_ingredient_simple_description
from database.db_connection import get_db_connection
from modules.fcm_notification import send_notification
from modules.preprocessing import preprocess_image
from modules.ocr import extract_text_from_image, extract_text_from_image_path, prewarm_ocr
from modules.auth_api import get_password_hash, router as auth_router
from sqlalchemy import text

API_MONITORING_KEY = os.getenv("MONITORING_API_KEY")


app = FastAPI()

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

@app.on_event("startup")
async def startup_event():
    print("\n" + "="*50)
    print("      WARMING UP MODELS (PRE-LOADING AI)      ")
    print("="*50)
    try:
        hf_token = os.getenv("HF_TOKEN") or os.getenv("HF_API_KEY")
        if hf_token:
            print("HF_TOKEN/HF_API_KEY ditemukan. Menggunakan Hugging Face Serverless API.")
            print("Menghindari pre-load model local SentenceTransformer untuk menghemat RAM.")
        else:
            from modules.embedding_utils import _get_model
            print("Pre-loading SentenceTransformer (embeddings) secara lokal...")
            _get_model()
    except Exception as e:
        print(f"Error pre-loading SentenceTransformer: {e}")

    print("OCR engine: PaddleOCR (on-device preprocessing + VPS inference)")

    # ── Pre-warm PaddleOCR ──────────────────────────────────────
    # Load model ke RAM saat startup agar request pertama tidak kena cold-start lag
    print("Pre-loading PaddleOCR model ke RAM...")
    try:
        prewarm_ocr()
        print("✅ PaddleOCR siap — model sudah di RAM.")
    except Exception as e:
        print(f"⚠️ Pre-warm PaddleOCR gagal: {e} (tidak kritis, akan di-load saat request pertama)")

    print("="*50 + "\n")

    # ── Start daily recurring notification scheduler ──────────────────────────
    def _check_recurring_notifications():
        """Called every minute by APScheduler. Sends repeat_daily notifications at their repeat_time."""
        try:
            from datetime import timedelta
            wib_tz = timezone(timedelta(hours=7))
            
            from database.db_connection import get_db_connection as _get_db
            db = _get_db()
            
            now_wib = datetime.now(wib_tz)
            now_str = now_wib.strftime("%H:%M")
            today_str = now_wib.strftime("%Y-%m-%d")

            candidates = db.get_recurring_notifications()
            for notif in candidates:
                repeat_time = (notif.get("repeat_time") or "").strip()
                if repeat_time != now_str:
                    continue

                # Skip if already sent today
                last_sent = notif.get("last_sent_at")
                if last_sent is not None:
                    if isinstance(last_sent, str):
                        last_sent_date = last_sent[:10]
                    else:
                        last_sent_date = last_sent.strftime("%Y-%m-%d")
                    if last_sent_date == today_str:
                        continue

                nid = notif["id"]
                title = notif.get("title") or ""
                body = notif.get("body") or ""
                data = notif.get("data")
                topic = notif.get("topic")
                tokens = notif.get("tokens")
                fcm_data: dict = {}
                if data and isinstance(data, dict):
                    fcm_data = {str(k): str(v) for k, v in data.items() if v is not None}

                try:
                    send_notification(
                        title=title,
                        body=body,
                        data=fcm_data,
                        topic=topic,
                        tokens=tokens,
                    )
                    db.update_last_sent_at(nid)
                    print(f"[Scheduler] Recurring notification #{nid} sent at {now_str}")
                except Exception as send_err:
                    print(f"[Scheduler] Failed to send recurring notification #{nid}: {send_err}")
        except Exception as outer_err:
            print(f"[Scheduler] Error in recurring check: {outer_err}")

    _recurring_scheduler = BackgroundScheduler(timezone="Asia/Jakarta")
    _recurring_scheduler.add_job(_check_recurring_notifications, "cron", minute="*")
    _recurring_scheduler.start()
    print("[Scheduler] Daily recurring notification scheduler started (checks every minute, WIB).")


# Make sure uploads directory exists
os.makedirs("uploads", exist_ok=True)
os.makedirs("uploads/profile_pictures", exist_ok=True)

# Serve uploaded files (profile pictures, temp uploads)
app.mount("/uploads", StaticFiles(directory="uploads"), name="uploads")


app.include_router(auth_router)

# model request untuk save history
class SaveHistoryRequest(BaseModel):
    analysis_id: int


def _resolve_user_id_from_request(request: Request, db) -> Optional[int]:
    auth_header = request.headers.get("authorization")
    if not auth_header or not auth_header.lower().startswith("bearer "):
        return None

    token = auth_header.split(" ")[1]
    try:
        payload = jwt.decode(token, SECRET_KEY, algorithms=[ALGORITHM])
    except JWTError:
        return None

    user_email = payload.get("sub")
    if not user_email:
        return None

    if not getattr(db, "engine", None):
        return None

    with db.engine.connect() as conn:
        user = conn.execute(
            text("SELECT id FROM users WHERE email = :email"),
            {"email": user_email},
        ).fetchone()
        if not user:
            return None
        return user.id if hasattr(user, "id") else user[0]


def _resolve_history_risk_level(risk_levels_csv: str | None) -> str:
    """Map ingredient risk distribution to UI-friendly badge values."""
    if not risk_levels_csv:
        return "safe"

    normalized = [part.strip().lower() for part in str(risk_levels_csv).split(",") if part and part.strip()]
    if any(level in {"high", "tinggi"} for level in normalized):
        return "high"
    if any(level in {"medium", "moderate", "sedang"} for level in normalized):
        return "moderate"
    if any(level in {"low", "rendah"} for level in normalized):
        return "safe"
    return "safe"

@app.post("/history/save")
def save_user_history(request_data: SaveHistoryRequest, request: Request, db=Depends(get_db_connection)):
    auth_header = request.headers.get("authorization")
    if not auth_header or not auth_header.lower().startswith("bearer "):
        raise HTTPException(status_code=401, detail="Missing or invalid Authorization header")
    token = auth_header.split(" ")[1]
    try:
        payload = jwt.decode(token, SECRET_KEY, algorithms=[ALGORITHM])
        user_email = payload.get("sub")
        if not user_email:
            raise HTTPException(status_code=401, detail="Invalid token")
    except JWTError as e:
        raise HTTPException(status_code=401, detail=f"Token error: {str(e)}")

    if not getattr(db, "engine", None):
        raise HTTPException(status_code=503, detail="Database unavailable")

    with db.engine.begin() as conn:
        user = conn.execute(
            text("SELECT id FROM users WHERE email = :email"),
            {"email": user_email}
        ).fetchone()
        if not user:
            raise HTTPException(status_code=404, detail="User not found")
        user_id = user.id if hasattr(user, 'id') else user[0]

        # Analysis harus dimiliki user yang sedang login.
        analysis = conn.execute(
            text("""
                SELECT a.id
                FROM analyses a
                INNER JOIN scans s ON s.id = a.scan_id
                WHERE a.id = :analysis_id
                  AND s.user_id = :user_id
                LIMIT 1
            """),
            {
                "analysis_id": request_data.analysis_id,
                "user_id": user_id,
            }
        ).fetchone()
        if not analysis:
            raise HTTPException(
                status_code=404,
                detail="Analysis not found or does not belong to this user",
            )

        conn.execute(text("""
            INSERT INTO user_histories (user_id, analysis_id)
            VALUES (:user_id, :analysis_id)
            ON DUPLICATE KEY UPDATE viewed_at = viewed_at
        """), {
            "user_id": user_id,
            "analysis_id": request_data.analysis_id,
        })

    return {
        "message": "Daftar histori telah berhasil ditambahkan.",
        "analysis_id": request_data.analysis_id,
    }


@app.post("/profile/upload")
async def upload_profile_picture(request: Request, file: UploadFile = File(...), db=Depends(get_db_connection)):
    """Upload profile picture file and save URL to user's `profile_picture` column."""
    user_id = _resolve_user_id_from_request(request, db)
    if not user_id:
        raise HTTPException(status_code=401, detail="Unauthorized")

    try:
        safe_fname = os.path.basename(file.filename) if file.filename else "profile.jpg"
        filename = f"user_{user_id}_{int(datetime.now().timestamp())}_{safe_fname}"
        save_path = os.path.join("uploads/profile_pictures", filename)
        with open(save_path, "wb") as f:
            content = await file.read()
            f.write(content)

        # Build absolute URL so frontend can load it directly
        base = str(request.base_url).rstrip("/")
        profile_url = f"{base}/uploads/profile_pictures/{filename}"

        with db.engine.begin() as conn:
            conn.execute(text(
                """
                UPDATE users
                SET profile_picture = :profile_picture
                WHERE id = :user_id
                """
            ), {
                "profile_picture": profile_url,
                "user_id": user_id,
            })

        return {"profile_picture": profile_url}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


class UpdateProfileRequest(BaseModel):
    name: Optional[str] = None
    email: Optional[str] = None
    profile_picture: Optional[str] = None
    password: Optional[str] = None
    fcm_token: Optional[str] = None


@app.post("/profile/update")
def update_profile(request_data: UpdateProfileRequest, request: Request, db=Depends(get_db_connection)):
    """Update user's profile fields: name, email, profile_picture, password."""
    user_id = _resolve_user_id_from_request(request, db)
    if not user_id:
        raise HTTPException(status_code=401, detail="Unauthorized")

    try:
        base = str(request.base_url).rstrip("/")

        # Normalize profile_picture input: if frontend sent a relative path, convert to absolute
        incoming_pp = (request_data.profile_picture or "").strip()
        if incoming_pp and incoming_pp.startswith("/uploads"):
            incoming_pp = f"{base}{incoming_pp}"

        with db.engine.begin() as conn:
            # Basic update using COALESCE/NULLIF to keep existing values when empty
            conn.execute(text(
                """
                UPDATE users
                SET
                    name = COALESCE(NULLIF(:name, ''), name),
                    email = COALESCE(NULLIF(:email, ''), email),
                    profile_picture = COALESCE(NULLIF(:profile_picture, ''), profile_picture),
                    password = COALESCE(NULLIF(:password, ''), password),
                    fcm_token = COALESCE(NULLIF(:fcm_token, ''), fcm_token)
                WHERE id = :user_id
                """
            ), {
                "name": request_data.name or "",
                "email": request_data.email or "",
                "profile_picture": incoming_pp or "",
                "password": request_data.password or "",
                "fcm_token": request_data.fcm_token or "",
                "user_id": user_id,
            })

            row = conn.execute(text("SELECT id, name, email, profile_picture, created_at FROM users WHERE id = :user_id"), {"user_id": user_id}).mappings().first()

        if not row:
            raise HTTPException(status_code=404, detail="User not found")

        # Ensure profile_picture returned is absolute URL
        pp = row.get("profile_picture")
        if pp and not pp.startswith("http"):
            pp = f"{base}{pp}" if pp.startswith("/") else f"{base}/{pp}"

        return {
            "id": row.get("id"),
            "name": row.get("name"),
            "email": row.get("email"),
            "profile_picture": pp,
            "created_at": row.get("created_at"),
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/profile/me")
def get_my_profile(request: Request, db=Depends(get_db_connection)):
    """Return current authenticated user's profile from DB for debugging/verification."""
    user_id = _resolve_user_id_from_request(request, db)
    if not user_id:
        raise HTTPException(status_code=401, detail="Unauthorized")

    try:
        base = str(request.base_url).rstrip("/")
        with db.engine.connect() as conn:
            row = conn.execute(text("SELECT id, name, email, profile_picture, created_at FROM users WHERE id = :user_id"), {"user_id": user_id}).mappings().first()

        if not row:
            raise HTTPException(status_code=404, detail="User not found")

        pp = row.get("profile_picture")
        if pp and not pp.startswith("http"):
            pp = f"{base}{pp}" if pp.startswith("/") else f"{base}/{pp}"

        return {
            "id": row.get("id"),
            "name": row.get("name"),
            "email": row.get("email"),
            "profile_picture": pp,
            "created_at": row.get("created_at"),
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

# model request dari Flutter
class IngredientRequest(BaseModel):
    text: str
    product_name: Optional[str] = None
    product_brand: Optional[str] = None
    product_category: Optional[str] = None


class HealthResponse(BaseModel):
    status: str
    services: Dict[str, Dict[str, Any]]
    timestamp: datetime


class MetricsSummaryResponse(BaseModel):
    analysis: Dict[str, Any]
    ingredients: Dict[str, Any]
    entities: Dict[str, Any] = Field(default_factory=dict)
    generated_at: datetime


class RecentAnalysisResponse(BaseModel):
    id: int
    scan_id: Optional[int] = None
    image_url: Optional[str] = None
    raw_text: Optional[str] = None
    summary: Optional[str] = None
    recommendation: Optional[str] = None
    status: Optional[str] = None
    matched_ingredient_count: Optional[int] = None
    matched_ingredients: Optional[List[str]] = None
    detail_count: Optional[int] = None
    user: Optional[Dict[str, Any]] = None
    product: Optional[Dict[str, Any]] = None
    ai_analysis: Optional[Dict[str, Any]] = None
    created_at: Optional[str] = None


class UserSummaryResponse(BaseModel):
    id: int
    name: Optional[str] = None
    email: Optional[str] = None
    role: Optional[str] = None
    provider: Optional[str] = None
    firebase_uid: Optional[str] = None
    profile_picture: Optional[str] = None
    fcm_token: Optional[str] = None
    device_token: Optional[str] = None
    analysis_count: int = 0
    last_analysis_at: Optional[str] = None
    created_at: Optional[str] = None


class ProductSummaryResponse(BaseModel):
    id: int
    name: Optional[str] = None
    brand: Optional[str] = None
    category: Optional[str] = None
    barcode: Optional[str] = None
    image_url: Optional[str] = None
    scan_count: int = 0
    analysis_count: int = 0
    created_at: Optional[str] = None


class IngredientSummaryResponse(BaseModel):
    id: int
    name: Optional[str] = None
    description: Optional[str] = None
    function: Optional[str] = None
    risk_level: Optional[str] = None
    created_at: Optional[str] = None


class AnalysisDetailSummaryResponse(BaseModel):
    id: int
    analysis_id: Optional[int] = None
    ingredient_id: Optional[int] = None
    ingredient_name: Optional[str] = None
    ingredient_risk_level: Optional[str] = None
    function: Optional[str] = None
    benefit: Optional[str] = None
    risk: Optional[str] = None
    analysis_status: Optional[str] = None
    analysis_created_at: Optional[str] = None


class UserHistorySummaryResponse(BaseModel):
    id: int
    user_id: Optional[int] = None
    user_name: Optional[str] = None
    user_email: Optional[str] = None
    analysis_id: Optional[int] = None
    analysis_status: Optional[str] = None
    product_name: Optional[str] = None
    product_brand: Optional[str] = None
    product_category: Optional[str] = None
    summary: Optional[str] = None
    recommendation: Optional[str] = None
    extracted_text: Optional[str] = None
    matched_ingredient_count: Optional[int] = None
    matched_ingredients: Optional[List[str]] = None
    analysis_created_at: Optional[str] = None
    viewed_at: Optional[str] = None

@app.get("/")
def root():
    return {"message": "Skincare Analyzer Backend Running"}


def require_monitoring_access(
    authorization: str | None = Header(default=None),
    x_api_key: str | None = Header(default=None),
):
    """Allow monitoring API key or a JWT issued to an admin account."""
    if API_MONITORING_KEY and x_api_key == API_MONITORING_KEY:
        return

    if authorization and authorization.lower().startswith("bearer "):
        token = authorization.split(" ", 1)[1]
        try:
            payload = jwt.decode(token, SECRET_KEY, algorithms=[ALGORITHM])
            if str(payload.get("role") or "").lower() == "admin":
                return
        except JWTError:
            pass

    raise HTTPException(status_code=401, detail="Admin authentication required")


def require_user_access(authorization: str | None = Header(default=None)):
    """Allow any authenticated user with a valid JWT."""
    if not authorization or not authorization.lower().startswith("bearer "):
        raise HTTPException(status_code=401, detail="Missing or invalid Authorization header")

    token = authorization.split(" ", 1)[1]
    try:
        payload = jwt.decode(token, SECRET_KEY, algorithms=[ALGORITHM])
    except JWTError as e:
        raise HTTPException(status_code=401, detail=f"Token error: {str(e)}")

    if not payload.get("sub"):
        raise HTTPException(status_code=401, detail="Invalid token")

    return payload


# ══════════════════════════════════════════════════════════════════════════════
# PRODUCT CATEGORIES — dibaca dari tabel `product_categories` di database.
# Admin dapat mengelola via endpoint /admin/categories (CRUD).
# Flutter app mengambil via GET /categories (hanya yang is_active=1).
# ══════════════════════════════════════════════════════════════════════════════

class CategoryCreateRequest(BaseModel):
    name:       str            = Field(..., min_length=1, max_length=100)
    icon:       Optional[str]  = Field(default="category", max_length=100)
    color:      Optional[str]  = Field(default="#4CB35B", max_length=20)
    sort_order: Optional[int]  = Field(default=0)

class CategoryUpdateRequest(BaseModel):
    name:       Optional[str] = Field(default=None, max_length=100)
    icon:       Optional[str] = Field(default=None, max_length=100)
    color:      Optional[str] = Field(default=None, max_length=20)
    sort_order: Optional[int] = Field(default=None)
    is_active:  Optional[int] = Field(default=None)


# ── Public: digunakan Flutter app ─────────────────────────────────────────────

@app.get("/categories")
def get_categories(db=Depends(get_db_connection)):
    """
    Mengembalikan daftar kategori aktif untuk dropdown scan di Flutter app.
    Hanya kategori dengan is_active = 1 yang ditampilkan, diurutkan by sort_order.
    """
    if not getattr(db, "engine", None):
        raise HTTPException(status_code=503, detail="Database unavailable")

    with db.engine.connect() as conn:
        rows = conn.execute(text(
            "SELECT id, name, icon, color, sort_order "
            "FROM product_categories "
            "WHERE is_active = 1 "
            "ORDER BY sort_order ASC, name ASC"
        )).fetchall()

    categories = [dict(r._mapping) for r in rows]
    return {"categories": categories, "total": len(categories)}


# ── Admin CRUD: semua endpoint butuh monitoring access ────────────────────────

@app.get("/admin/categories", dependencies=[Depends(require_monitoring_access)])
def admin_list_categories(
    include_inactive: bool = Query(default=False),
    db=Depends(get_db_connection),
):
    """List semua kategori (termasuk nonaktif jika include_inactive=true)."""
    if not getattr(db, "engine", None):
        raise HTTPException(status_code=503, detail="Database unavailable")

    with db.engine.connect() as conn:
        query = (
            "SELECT id, name, icon, color, sort_order, is_active, created_at, updated_at "
            "FROM product_categories "
        )
        if not include_inactive:
            query += "WHERE is_active = 1 "
        query += "ORDER BY sort_order ASC, name ASC"
        rows = conn.execute(text(query)).fetchall()

    return {
        "categories": [dict(r._mapping) for r in rows],
        "total": len(rows),
    }


@app.post("/admin/categories", dependencies=[Depends(require_monitoring_access)])
def admin_create_category(data: CategoryCreateRequest, db=Depends(get_db_connection)):
    """Tambah kategori baru. Name harus unik."""
    if not getattr(db, "engine", None):
        raise HTTPException(status_code=503, detail="Database unavailable")

    with db.engine.begin() as conn:
        # Cek duplikat
        existing = conn.execute(
            text("SELECT id FROM product_categories WHERE name = :name"),
            {"name": data.name.strip()},
        ).fetchone()
        if existing:
            raise HTTPException(status_code=409, detail=f"Kategori '{data.name}' sudah ada.")

        result = conn.execute(
            text(
                "INSERT INTO product_categories (name, icon, color, sort_order) "
                "VALUES (:name, :icon, :color, :sort_order)"
            ),
            {
                "name":       data.name.strip(),
                "icon":       data.icon or "category",
                "color":      data.color or "#4CB35B",
                "sort_order": data.sort_order or 0,
            },
        )
        new_id = result.lastrowid

    return {
        "message": "Kategori berhasil ditambahkan.",
        "id": new_id,
        "name": data.name.strip(),
    }


@app.put("/admin/categories/{category_id}", dependencies=[Depends(require_monitoring_access)])
def admin_update_category(
    category_id: int,
    data: CategoryUpdateRequest,
    db=Depends(get_db_connection),
):
    """Edit nama, icon, warna, urutan, atau status aktif suatu kategori."""
    if not getattr(db, "engine", None):
        raise HTTPException(status_code=503, detail="Database unavailable")

    with db.engine.begin() as conn:
        # Pastikan kategori ada
        existing = conn.execute(
            text("SELECT id FROM product_categories WHERE id = :id"),
            {"id": category_id},
        ).fetchone()
        if not existing:
            raise HTTPException(status_code=404, detail="Kategori tidak ditemukan.")

        # Bangun SET clause secara dinamis dari field yang dikirim
        set_parts = []
        params: Dict[str, Any] = {"id": category_id}

        if data.name is not None:
            set_parts.append("name = :name")
            params["name"] = data.name.strip()
        if data.icon is not None:
            set_parts.append("icon = :icon")
            params["icon"] = data.icon
        if data.color is not None:
            set_parts.append("color = :color")
            params["color"] = data.color
        if data.sort_order is not None:
            set_parts.append("sort_order = :sort_order")
            params["sort_order"] = data.sort_order
        if data.is_active is not None:
            set_parts.append("is_active = :is_active")
            params["is_active"] = data.is_active

        if not set_parts:
            raise HTTPException(status_code=400, detail="Tidak ada field yang diubah.")

        conn.execute(
            text(f"UPDATE product_categories SET {', '.join(set_parts)} WHERE id = :id"),
            params,
        )

    return {"message": "Kategori berhasil diperbarui.", "id": category_id}


@app.delete("/admin/categories/{category_id}", dependencies=[Depends(require_monitoring_access)])
def admin_delete_category(category_id: int, db=Depends(get_db_connection)):
    """
    Soft-delete: set is_active = 0 (kategori tidak muncul di app).
    Data histori scan yang menggunakan kategori ini tetap aman.
    """
    if not getattr(db, "engine", None):
        raise HTTPException(status_code=503, detail="Database unavailable")

    with db.engine.begin() as conn:
        existing = conn.execute(
            text("SELECT id, name FROM product_categories WHERE id = :id"),
            {"id": category_id},
        ).fetchone()
        if not existing:
            raise HTTPException(status_code=404, detail="Kategori tidak ditemukan.")

        conn.execute(
            text("UPDATE product_categories SET is_active = 0 WHERE id = :id"),
            {"id": category_id},
        )

    return {
        "message": f"Kategori '{existing.name}' berhasil dinonaktifkan.",
        "id": category_id,
    }


@app.post(
    "/admin/categories/{category_id}/restore",
    dependencies=[Depends(require_monitoring_access)],
)
def admin_restore_category(category_id: int, db=Depends(get_db_connection)):
    """Aktifkan kembali kategori yang sebelumnya dinonaktifkan."""
    if not getattr(db, "engine", None):
        raise HTTPException(status_code=503, detail="Database unavailable")

    with db.engine.begin() as conn:
        existing = conn.execute(
            text("SELECT id, name FROM product_categories WHERE id = :id"),
            {"id": category_id},
        ).fetchone()
        if not existing:
            raise HTTPException(status_code=404, detail="Kategori tidak ditemukan.")

        conn.execute(
            text("UPDATE product_categories SET is_active = 1 WHERE id = :id"),
            {"id": category_id},
        )

    return {
        "message": f"Kategori '{existing.name}' berhasil diaktifkan kembali.",
        "id": category_id,
    }

@app.post("/analyze")
def analyze_ingredients(data: IngredientRequest, request: Request):
    raw_text = data.text
    print("\n" + "="*50)
    print("      TEKS OCR MENTAH DITERIMA DARI APLIKASI      ")
    print("="*50)
    print(raw_text)
    print("="*50 + "\n")
    db = get_db_connection()
    user_id = _resolve_user_id_from_request(request, db)
    return process_text_analysis(
        raw_text,
        user_id=user_id,
        product_name=data.product_name,
        product_brand=data.product_brand,
        product_category=data.product_category,
    )


@app.get("/analysis-history")
def analysis_history(limit: int = Query(default=10, ge=1, le=100)):
    db = get_db_connection()
    return {"items": db.get_recent_analysis_results(limit=limit)}


@app.get("/analysis/{analysis_id}")
def analysis_detail(analysis_id: int):
    db = get_db_connection()
    detail = db.get_analysis_detail(analysis_id=analysis_id)
    if not detail:
        raise HTTPException(status_code=404, detail="Analysis data not found")
    return detail

@app.post("/analyze-image")
async def analyze_image(
    request: Request,
    file: UploadFile = File(...),
    product_name: str | None = Form(default=None),
    product_brand: str | None = Form(default=None),
    product_category: str | None = Form(default=None),
):
    """Receives an image for OCR, then processes the text."""
    try:
        import uuid
        # Save file safely to a permanent scan directory
        safe_name = os.path.basename(file.filename) if file.filename else "upload.jpg"
        ext = os.path.splitext(safe_name)[1]
        if not ext: ext = ".jpg"
        unique_filename = f"scan_{int(time.time())}_{uuid.uuid4().hex[:8]}{ext}"
        scan_dir = os.path.join("uploads", "scans")
        os.makedirs(scan_dir, exist_ok=True)
        final_path = os.path.join(scan_dir, unique_filename)
        
        with open(final_path, "wb") as buffer:
            shutil.copyfileobj(file.file, buffer)
        
        # 1. OCR Preprocessing and Extraction (routes to PaddleOCR if configured, otherwise falls back to Tesseract)
        start_time = time.time()
        extracted_text = extract_text_from_image_path(final_path)
        exec_time_ms = int((time.time() - start_time) * 1000)
        
        print("\n" + "="*60)
        print(f"📷 [SCAN APK RESULT] File Uploaded: {unique_filename} | ⏱️ Waktu OCR: {exec_time_ms} ms")
        print("-" * 60)
        print(f"📑 Teks Hasil OCR:\n{extracted_text.strip() if extracted_text.strip() else '(Kosong / Tidak ada teks)'}")
        print("="*60 + "\n")
        
        # WE NO LONGER DELETE THE IMAGE HERE. It's saved for history.
        image_url = f"/uploads/scans/{unique_filename}"
            
        if not extracted_text.strip():
            raise HTTPException(status_code=400, detail="Could not extract text from the image.")
            
        # 2. Process text through the existing pipeline
        db = get_db_connection()
        user_id = _resolve_user_id_from_request(request, db)
        return process_text_analysis(
            extracted_text,
            user_id=user_id,
            product_name=product_name,
            product_brand=product_brand,
            product_category=product_category,
            image_url=image_url,
        )
        
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

def process_text_analysis(
    raw_text: str,
    user_id: Optional[int] = None,
    product_name: Optional[str] = None,
    product_brand: Optional[str] = None,
    product_category: Optional[str] = None,
    image_url: Optional[str] = None,
):
    """Helper function to run the NLP/AI pipeline on text."""
    # 1. Keep only ingredient-like text for downstream AI and matching
    ingredient_text = extract_ingredient_text(raw_text)

    # 2. Text cleaning/tokenization
    cleaned_tokens = clean_text_pipeline(ingredient_text)
    
    # 3. Persiapkan database connection & data ingredients dari MySQL
    db = get_db_connection()
    db_ingredients = db.get_all_ingredients()
    
    # 4. Ingredient matching
    matched_ingredients = match_tokens_to_db(cleaned_tokens, db_ingredients)
    
    matched_names = [m.get("name") for m in matched_ingredients if m.get("status") != "Unknown"]
    print(f"🔬 [NLP ANALYSIS] Total Tokens ({len(cleaned_tokens)}): {cleaned_tokens[:10]}...")
    print(f"✅ [INGREDIENT MATCHING] Berhasil Dikenali ({len(matched_names)} bahan): {matched_names}\n")
    
    # 5. Enrich matched ingredients with dataset descriptions
    # Tambahkan deskripsi singkat dari dataset RAG untuk setiap ingredient
    qdrant_client = None
    try:
        from modules.qdrant_client_factory import get_qdrant_client
        qdrant_client = get_qdrant_client()
    except Exception as e:
        print(f"Failed to initialize Qdrant client for enriching ingredients: {e}")

    for ingredient in matched_ingredients:
        ingredient_name = ingredient.get("name", "")
        dataset_info = get_ingredient_simple_description(ingredient_name, client=qdrant_client)
        
        if dataset_info and dataset_info.get("found_in_dataset"):
            # Tambahkan info dari dataset
            ingredient["dataset_description"] = dataset_info.get("simple_description", "")
            ingredient["dataset_functions"] = dataset_info.get("functions", "")
            ingredient["dataset_warnings"] = dataset_info.get("warnings", "")
            ingredient["dataset_origin"] = dataset_info.get("origin", "")
            ingredient["dataset_harmful"] = dataset_info.get("harmful", False)
            ingredient["dataset_bpom_warning"] = dataset_info.get("bpom_warning", "")
            ingredient["dataset_sources"] = dataset_info.get("sources", [])
            ingredient["found_in_dataset"] = True
        else:
            # Tidak ditemukan di dataset
            ingredient["dataset_description"] = ""
            ingredient["dataset_functions"] = ""
            ingredient["dataset_warnings"] = ""
            ingredient["dataset_origin"] = ""
            ingredient["dataset_harmful"] = False
            ingredient["dataset_bpom_warning"] = ""
            ingredient["dataset_sources"] = []
            ingredient["found_in_dataset"] = False

    if qdrant_client is not None:
        try:
            qdrant_client.close()
        except Exception:
            pass

    # 6. Rule-based expert analysis
    expert_report = run_expert_system(matched_ingredients)
    
    # 7. Gemini AI analysis with model fallback + dataset-grounded prompt
    with concurrent.futures.ThreadPoolExecutor(max_workers=2) as executor:
        future_ai = executor.submit(
            analyze_ingredients_with_ai,
            text=ingredient_text,
            ingredient_tokens=cleaned_tokens,
            matched_ingredients=matched_ingredients,
            include_metadata=True,
        )
        future_simple = executor.submit(
            generate_simple_descriptions,
            matched_ingredients=matched_ingredients
        )
        
        ai_result_payload = future_ai.result()
        simple_descriptions_map = future_simple.result()

    # Mapped simple descriptions (only for ingredients that don't already have one from Qdrant)
    for ing in matched_ingredients:
        name = str(ing.get("name") or ing.get("ocr_token_used") or "").upper().strip()
        if name in simple_descriptions_map and not (ing.get("dataset_description") or "").strip():
            ing["dataset_description"] = simple_descriptions_map[name]


    if isinstance(ai_result_payload, dict):
        ai_result_text = str(ai_result_payload.get("text") or "")
        ai_model_used = ai_result_payload.get("model")
        ai_models_tried = ai_result_payload.get("models_tried") or []
    else:
        ai_result_text = str(ai_result_payload)
        ai_model_used = None
        ai_models_tried = []

    summary_text = _build_summary_text(expert_report)
    recommendation_text = _build_recommendation_text(expert_report, ai_result_text)

    # Membentuk dictionary final (JSON Result -> Flutter)
    result_data = {
        "input_text": raw_text,
        "ingredient_text_used": ingredient_text,
        "cleaned_tokens": cleaned_tokens,
        "matched_ingredients": matched_ingredients,
        "expert_analysis": expert_report,
        "summary": summary_text,
        "recommendation": recommendation_text,
        "ai_analysis": {
            "model_output": ai_result_text,
            "model_used": ai_model_used,
            "models_tried": ai_models_tried,
        },
    }

    if product_name or product_brand or product_category:
        result_data["product"] = {
            "name": product_name,
            "brand": product_brand,
            "category": product_category,
        }

    # 8. MySQL Database (Laragon) - Simpan hasil analisis
    # Note: DB schema must align
    saved_id = db.save_analysis_result(
        raw_text=raw_text,
        ai_result=result_data,
        matched_ingredients=matched_ingredients,
        expert_report=expert_report,
        user_id=user_id,
        product_name=product_name,
        product_brand=product_brand,
        product_category=product_category,
        image_url=image_url,
    )
    if saved_id:
        result_data["analysis_id"] = saved_id

    return result_data


# ─── Product Recommendations (INCIDecoder Dataset) ───────────────────────────
# Delegates to modules/product_recommender.py which implements:
#   - Strategy 1: Qdrant semantic similarity search
#   - Strategy 2: String-overlap fallback
#   - 'auto' mode: semantic first, fallback to overlap if < 3 results

from modules.product_recommender import get_recommendations as _recommender_get
from modules.product_recommender import set_ingesting as _set_ingesting


@app.get("/recommendations")
def get_recommendations(
    ingredients: str = Query(..., description="Comma-separated ingredient names from scan result"),
    limit: int = Query(default=8, ge=1, le=20),
    mode: str = Query(
        default="auto",
        description="Recommendation strategy: 'auto' (semantic + fallback), 'semantic', 'overlap'",
    ),
    category: Optional[str] = Query(default=None, description="Category of the scanned product"),
    skin_type: Optional[str] = Query(default=None, description="Skin type of the user"),
    skin_concern: Optional[str] = Query(default=None, description="Primary skin concern of the user"),
):
    """
    Return top-N similar products from the INCIDecoder dataset with personalized matching and compatibility checks.
    """
    ingredient_names = [i.strip() for i in ingredients.split(",") if i.strip()]
    if not ingredient_names:
        return {
            "recommendations": [],
            "compatibility_tips": {"conflicts": [], "synergies": []},
            "routine_tip": "",
            "mode_used": mode
        }

    valid_modes = {"auto", "semantic", "overlap"}
    if mode not in valid_modes:
        mode = "auto"

    result = _recommender_get(
        ingredient_names,
        limit=limit,
        mode=mode,
        category=category,
        skin_type=skin_type,
        skin_concern=skin_concern
    )
    
    return {
        "recommendations": result.get("recommendations", []),
        "compatibility_tips": result.get("compatibility_tips", {"conflicts": [], "synergies": []}),
        "routine_tip": result.get("routine_tip", ""),
        "mode_used": mode,
        "skin_type_used": skin_type,
        "skin_concern_used": skin_concern
    }


def _build_summary_text(expert_report: Dict[str, Any]) -> str:
    total_identified = expert_report.get("total_ingredients_identified", 0)
    unknown_count = expert_report.get("total_unknown", 0)
    return (
        f"Bahan dikenali: {total_identified}. Belum dikenali: {unknown_count}."
    )


def _build_recommendation_text(expert_report: Dict[str, Any], ai_text: str) -> str:
    cleaned_ai = (ai_text or "").strip()
    if cleaned_ai:
        return cleaned_ai

    return "Secara umum formula cukup aman, tetap perhatikan kecocokan dengan jenis kulit Anda."



@app.post("/admin/reingest")
def admin_reingest(_: None = Depends(require_monitoring_access)):
    """
    Trigger re-ingestion of all datasets into Qdrant dari dalam backend.
    Berjalan dalam proses yang SAMA sehingga tidak ada konflik file lock.
    Selama proses ingest, /recommendations fallback ke string-overlap otomatis.

    Cara panggil:
        curl -X POST http://VPS_IP:8000/admin/reingest \\
             -H "X-Api-Key: YOUR_MONITORING_KEY"
    """
    import threading
    from modules.qdrant_setup import setup_qdrant
    from modules.product_recommender import clear_recommender_cache

    def _run_ingest():
        _set_ingesting(True)
        try:
            print("[reingest] Starting Qdrant re-ingestion...")
            setup_qdrant()
            clear_recommender_cache()
            print("[reingest] Done.")
        except Exception as e:
            print(f"[reingest] ERROR: {e}")
        finally:
            _set_ingesting(False)

    t = threading.Thread(target=_run_ingest, daemon=True, name="qdrant-reingest")
    t.start()

    return {
        "status": "started",
        "message": (
            "Re-ingestion berjalan di background. "
            "Selama proses, /recommendations menggunakan string-overlap fallback. "
            "Proses selesai dalam beberapa menit."
        ),
    }


def _current_timestamp() -> datetime:
    return datetime.now(timezone.utc)


def _service_status(healthy: bool, detail: str = "") -> Dict[str, Any]:
    return {
        "status": "up" if healthy else "down",
        "detail": detail,
    }


@app.get("/health", response_model=HealthResponse)
def health_status(_: None = Depends(require_monitoring_access)):
    db = get_db_connection()
    db_status = db.ping()
    ocr_ready = shutil.which("tesseract") is not None
    gemini_ready = bool(os.getenv("GEMINI_API_KEY"))

    services = {
        "database": _service_status(db_status),
        "ocr": _service_status(ocr_ready, "Tesseract binary not found" if not ocr_ready else ""),
        "gemini_ai": _service_status(gemini_ready, "Missing GEMINI_API_KEY" if not gemini_ready else ""),
    }

    overall_status = "up" if all(service["status"] == "up" for service in services.values()) else "degraded"

    return HealthResponse(status=overall_status, services=services, timestamp=_current_timestamp())


@app.get("/metrics/summary", response_model=MetricsSummaryResponse)
def metrics_summary(_: None = Depends(require_monitoring_access)):
    db = get_db_connection()
    analysis = db.get_analysis_summary()
    ingredients = db.get_ingredient_summary()
    entities = db.get_entity_summary()
    return MetricsSummaryResponse(
        analysis=analysis,
        ingredients=ingredients,
        entities=entities,
        generated_at=_current_timestamp(),
    )


@app.get("/metrics/recent", response_model=List[RecentAnalysisResponse])
def metrics_recent(
    limit: int = Query(default=15, ge=1, le=100),
    _: None = Depends(require_monitoring_access),
):
    db = get_db_connection()
    records = db.get_recent_analysis_results(limit=limit)
    # FastAPI will coerce dict list into the response model
    return records


@app.get("/metrics/users", response_model=List[UserSummaryResponse])
def metrics_users(
    limit: int = Query(default=1000, ge=1, le=5000),
    _: None = Depends(require_monitoring_access),
):
    db = get_db_connection()
    return db.get_users(limit=limit)


class AdminUserCreateRequest(BaseModel):
    name: Optional[str] = None
    email: EmailStr
    password: str
    role: Optional[str] = "user"
    provider: Optional[str] = "manual"
    firebase_uid: Optional[str] = None


class AdminUserUpdateRequest(BaseModel):
    name: Optional[str] = None
    email: Optional[EmailStr] = None
    password: Optional[str] = None
    role: Optional[str] = None
    provider: Optional[str] = None
    firebase_uid: Optional[str] = None
    profile_picture: Optional[str] = None
    fcm_token: Optional[str] = None
    device_token: Optional[str] = None


def _normalize_optional_text(value: Optional[str]) -> Optional[str]:
    if value is None:
        return None
    normalized = str(value).strip()
    return normalized or None


def _validate_admin_user_password(password: str) -> None:
    if len(password) < 8:
        raise HTTPException(status_code=400, detail="Password minimal 8 karakter")


@app.get("/admin/users", dependencies=[Depends(require_monitoring_access)])
def admin_list_users(limit: int = Query(default=1000, ge=1, le=5000), db=Depends(get_db_connection)):
    return {"items": db.get_users(limit=limit)}


@app.post("/admin/users", dependencies=[Depends(require_monitoring_access)])
def admin_create_user(payload: AdminUserCreateRequest, db=Depends(get_db_connection)):
    email = str(payload.email).strip().lower()
    if db.get_admin_user_by_email(email):
        raise HTTPException(status_code=400, detail="Email sudah terdaftar")

    _validate_admin_user_password(payload.password)
    user_id = db.create_admin_user(
        name=_normalize_optional_text(payload.name),
        email=email,
        password_hash=get_password_hash(payload.password),
        role=_normalize_optional_text(payload.role) or "user",
        provider=_normalize_optional_text(payload.provider) or "manual",
        firebase_uid=_normalize_optional_text(payload.firebase_uid),
    )
    if not user_id:
        raise HTTPException(status_code=500, detail="Failed to create user")

    return db.get_admin_user_by_id(user_id) or {"id": user_id}


@app.get("/admin/users/{user_id}", dependencies=[Depends(require_monitoring_access)])
def admin_get_user(user_id: int, db=Depends(get_db_connection)):
    user = db.get_admin_user_by_id(user_id)
    if not user:
        raise HTTPException(status_code=404, detail="User not found")
    return user


@app.put("/admin/users/{user_id}", dependencies=[Depends(require_monitoring_access)])
def admin_update_user(user_id: int, payload: AdminUserUpdateRequest, db=Depends(get_db_connection)):
    user = db.get_admin_user_by_id(user_id)
    if not user:
        raise HTTPException(status_code=404, detail="User not found")

    email = str(payload.email).strip().lower() if payload.email else None
    if email:
        existing = db.get_admin_user_by_email(email)
        if existing and int(existing.get("id") or 0) != user_id:
            raise HTTPException(status_code=400, detail="Email sudah terdaftar")

    password_hash = None
    if payload.password is not None and payload.password.strip():
        _validate_admin_user_password(payload.password)
        password_hash = get_password_hash(payload.password)

    ok = db.update_admin_user(
        user_id=user_id,
        name=_normalize_optional_text(payload.name),
        email=email,
        password_hash=password_hash,
        role=_normalize_optional_text(payload.role),
        provider=_normalize_optional_text(payload.provider),
        firebase_uid=_normalize_optional_text(payload.firebase_uid),
        profile_picture=_normalize_optional_text(payload.profile_picture),
        fcm_token=_normalize_optional_text(payload.fcm_token),
        device_token=_normalize_optional_text(payload.device_token),
    )
    if not ok:
        raise HTTPException(status_code=500, detail="Failed to update user")

    return db.get_admin_user_by_id(user_id) or {"id": user_id}


@app.delete("/admin/users/{user_id}", dependencies=[Depends(require_monitoring_access)])
def admin_delete_user(user_id: int, db=Depends(get_db_connection)):
    user = db.get_admin_user_by_id(user_id)
    if not user:
        raise HTTPException(status_code=404, detail="User not found")
    ok = db.delete_admin_user(user_id)
    if not ok:
        raise HTTPException(status_code=500, detail="Failed to delete user")
    return {"status": "deleted"}


@app.get("/api/dermify/admin/users", dependencies=[Depends(require_monitoring_access)])
def alias_list_users(limit: int = Query(default=1000, ge=1, le=5000), db=Depends(get_db_connection)):
    return admin_list_users(limit, db)


@app.post("/api/dermify/admin/users", dependencies=[Depends(require_monitoring_access)])
def alias_create_user(payload: AdminUserCreateRequest, db=Depends(get_db_connection)):
    return admin_create_user(payload, db)


@app.get("/api/dermify/admin/users/{user_id}", dependencies=[Depends(require_monitoring_access)])
def alias_get_user(user_id: int, db=Depends(get_db_connection)):
    return admin_get_user(user_id, db)


@app.put("/api/dermify/admin/users/{user_id}", dependencies=[Depends(require_monitoring_access)])
def alias_update_user(user_id: int, payload: AdminUserUpdateRequest, db=Depends(get_db_connection)):
    return admin_update_user(user_id, payload, db)


@app.delete("/api/dermify/admin/users/{user_id}", dependencies=[Depends(require_monitoring_access)])
def alias_delete_user(user_id: int, db=Depends(get_db_connection)):
    return admin_delete_user(user_id, db)


@app.get("/metrics/analyses", response_model=List[RecentAnalysisResponse])
def metrics_analyses(
    limit: int = Query(default=1000, ge=1, le=5000),
    _: None = Depends(require_monitoring_access),
):
    db = get_db_connection()
    return db.get_analyses(limit=limit)


@app.get("/metrics/analysis-details", response_model=List[AnalysisDetailSummaryResponse])
def metrics_analysis_details(
    limit: int = Query(default=1000, ge=1, le=5000),
    _: None = Depends(require_monitoring_access),
):
    db = get_db_connection()
    return db.get_analysis_details(limit=limit)


@app.get("/metrics/products", response_model=List[ProductSummaryResponse])
def metrics_products(
    limit: int = Query(default=1000, ge=1, le=5000),
    _: None = Depends(require_monitoring_access),
):
    db = get_db_connection()
    return db.get_products(limit=limit)


# --- Admin Product CRUD endpoints ---
class ProductCreateRequest(BaseModel):
    name: str
    brand: Optional[str] = None
    category: Optional[str] = None
    barcode: Optional[str] = None
    image_url: Optional[str] = None


class ProductUpdateRequest(BaseModel):
    name: Optional[str] = None
    brand: Optional[str] = None
    category: Optional[str] = None
    barcode: Optional[str] = None
    image_url: Optional[str] = None


@app.post("/admin/products", dependencies=[Depends(require_monitoring_access)])
def admin_create_product(payload: ProductCreateRequest, db=Depends(get_db_connection)):
    product_id = db.create_product(
        payload.name.strip(),
        (payload.brand or '').strip() or None,
        (payload.category or '').strip() or None,
        (payload.barcode or '').strip() or None,
        (payload.image_url or '').strip() or None,
    )
    if not product_id:
        raise HTTPException(status_code=500, detail="Failed to create product")
    return {"id": product_id}


@app.get("/admin/products/{product_id}", dependencies=[Depends(require_monitoring_access)])
def admin_get_product(product_id: int, db=Depends(get_db_connection)):
    product = db.get_product_by_id(product_id)
    if not product:
        raise HTTPException(status_code=404, detail="Product not found")
    return product


@app.put("/admin/products/{product_id}", dependencies=[Depends(require_monitoring_access)])
def admin_update_product(product_id: int, payload: ProductUpdateRequest, db=Depends(get_db_connection)):
    ok = db.update_product(product_id, payload.name, payload.brand, payload.category, payload.barcode, payload.image_url)
    if not ok:
        raise HTTPException(status_code=500, detail="Failed to update product")
    return {"status": "ok"}


@app.delete("/admin/products/{product_id}", dependencies=[Depends(require_monitoring_access)])
def admin_delete_product(product_id: int, db=Depends(get_db_connection)):
    ok = db.delete_product(product_id)
    if not ok:
        raise HTTPException(status_code=500, detail="Failed to delete product")
    return {"status": "deleted"}


# --- Admin Ingredient CRUD endpoints ---
class IngredientCreateRequest(BaseModel):
    name: str
    description: Optional[str] = None
    function: Optional[str] = None
    risk_level: Optional[str] = None


class IngredientUpdateRequest(BaseModel):
    name: Optional[str] = None
    description: Optional[str] = None
    function: Optional[str] = None
    risk_level: Optional[str] = None


@app.post("/admin/ingredients", dependencies=[Depends(require_monitoring_access)])
def admin_create_ingredient(payload: IngredientCreateRequest, db=Depends(get_db_connection)):
    name = payload.name.strip()
    if not name:
        raise HTTPException(status_code=400, detail="Ingredient name is required")
    ing_id = db.create_ingredient(name, (payload.description or '').strip() or None, (payload.function or '').strip() or None, (payload.risk_level or '').strip() or None)
    if not ing_id:
        raise HTTPException(status_code=500, detail="Failed to create ingredient")
    return {"id": ing_id}


@app.get("/admin/ingredients/{ingredient_id}", dependencies=[Depends(require_monitoring_access)])
def admin_get_ingredient(ingredient_id: int, db=Depends(get_db_connection)):
    ing = db.get_ingredient_by_id(ingredient_id)
    if not ing:
        raise HTTPException(status_code=404, detail="Ingredient not found")
    return ing


@app.put("/admin/ingredients/{ingredient_id}", dependencies=[Depends(require_monitoring_access)])
def admin_update_ingredient(ingredient_id: int, payload: IngredientUpdateRequest, db=Depends(get_db_connection)):
    ok = db.update_ingredient(ingredient_id, payload.name, payload.description, payload.function, payload.risk_level)
    if not ok:
        raise HTTPException(status_code=500, detail="Failed to update ingredient")
    return {"status": "ok"}


@app.delete("/admin/ingredients/{ingredient_id}", dependencies=[Depends(require_monitoring_access)])
def admin_delete_ingredient(ingredient_id: int, db=Depends(get_db_connection)):
    ok = db.delete_ingredient(ingredient_id)
    if not ok:
        raise HTTPException(status_code=500, detail="Failed to delete ingredient")
    return {"status": "deleted"}


@app.get("/metrics/ingredients", response_model=List[IngredientSummaryResponse])
def metrics_ingredients(
    limit: int = Query(default=1000, ge=1, le=5000),
    _: None = Depends(require_monitoring_access),
):
    db = get_db_connection()
    return db.get_ingredients(limit=limit)


@app.get("/mobile/metrics/ingredients", response_model=List[IngredientSummaryResponse])
def mobile_metrics_ingredients(
    limit: int = Query(default=1000, ge=1, le=5000),
    _: Dict[str, Any] = Depends(require_user_access),
):
    db = get_db_connection()
    return db.get_ingredients(limit=limit)


@app.get("/metrics/user-histories", response_model=List[UserHistorySummaryResponse])
def metrics_user_histories(
    limit: int = Query(default=1000, ge=1, le=5000),
    _: None = Depends(require_monitoring_access),
):
    db = get_db_connection()
    return db.get_user_histories(limit=limit)


# --- Admin Notifications CRUD endpoints ---
class NotificationCreateRequest(BaseModel):
    title: str
    body: Optional[str] = None
    # Accept either an object/dict or a JSON string from the frontend
    data: Optional[object] = None
    topic: Optional[str] = None
    user_id: Optional[int] = None
    target_user_id: Optional[int] = None
    # Accept either a list of tokens or a JSON string
    tokens: Optional[object] = None
    status: Optional[str] = "draft"
    scheduled_at: Optional[str] = None
    repeat_daily: Optional[bool] = False
    repeat_time: Optional[str] = None  # format "HH:MM" (WIB)


def _normalize_notification_tokens(tokens_field: Any) -> Optional[List[str]]:
    if tokens_field is None:
        return None
    if isinstance(tokens_field, str):
        try:
            tokens_field = json.loads(tokens_field)
        except Exception:
            tokens_field = [t.strip() for t in tokens_field.split(",") if t.strip()]
    if isinstance(tokens_field, list):
        tokens = [str(token).strip() for token in tokens_field if str(token).strip()]
        return tokens or None
    return None


def _extract_target_user_id(payload: Dict[str, Any], data_field: Any = None) -> Optional[int]:
    raw_target = payload.get("target_user_id") or payload.get("user_id")
    if raw_target is None and isinstance(data_field, dict):
        raw_target = data_field.get("target_user_id") or data_field.get("user_id")
    if raw_target in (None, ""):
        return None
    try:
        target_user_id = int(raw_target)
    except (TypeError, ValueError):
        raise HTTPException(status_code=400, detail="target_user_id harus berupa angka")
    if target_user_id <= 0:
        raise HTTPException(status_code=400, detail="target_user_id tidak valid")
    return target_user_id


def _prepare_notification_target(
    payload: Dict[str, Any],
    data_field: Any,
    topic: Optional[str],
    tokens_field: Optional[List[str]],
    db,
    require_tokens: bool = False,
) -> tuple[Any, Optional[str], Optional[List[str]], Optional[int]]:
    target_user_id = _extract_target_user_id(payload, data_field)
    if not target_user_id:
        return data_field, topic, tokens_field, None

    if not isinstance(data_field, dict):
        data_field = {} if data_field in (None, "") else {"payload": str(data_field)}

    data_field["target_user_id"] = target_user_id
    data_field["user_id"] = target_user_id

    target_user = db.get_admin_user_by_id(target_user_id)
    if not target_user:
        raise HTTPException(status_code=404, detail="Target user not found")

    resolved_tokens = tokens_field or db.get_user_notification_tokens(target_user_id)
    if require_tokens and not resolved_tokens:
        raise HTTPException(
            status_code=400,
            detail="User ini belum punya token notifikasi. Login dari aplikasi mobile dulu atau simpan FCM token user.",
        )

    return data_field, None, resolved_tokens, target_user_id


def _stringify_fcm_data(data_field: Any) -> Dict[str, str]:
    fcm_data: Dict[str, str] = {}
    if data_field and isinstance(data_field, dict):
        for k, v in data_field.items():
            if v is not None:
                fcm_data[str(k)] = str(v)
    return fcm_data


@app.get("/admin/notifications", dependencies=[Depends(require_monitoring_access)])
def admin_list_notifications(limit: int = Query(default=50, ge=1, le=500), offset: int = Query(default=0, ge=0), db=Depends(get_db_connection)):
    items = db.get_notifications(limit=limit, offset=offset)
    return {"items": items}


@app.get("/admin/notifications/{notification_id}", dependencies=[Depends(require_monitoring_access)])
def admin_get_notification(notification_id: int, db=Depends(get_db_connection)):
    n = db.get_notification_by_id(notification_id)
    if not n:
        raise HTTPException(status_code=404, detail="Notification not found")
    return n


@app.post("/admin/notifications", dependencies=[Depends(require_monitoring_access)])
def admin_create_notification(payload: dict, db=Depends(get_db_connection)):
    # Accept raw JSON body (frontend may send stringified fields). Normalize below.
    try:
        print(f"[admin_create_notification] raw payload={payload}")
    except Exception:
        print("[admin_create_notification] raw payload=<unserializable>")

    title = str(payload.get("title") or "").strip()
    if not title:
        raise HTTPException(status_code=400, detail="title is required")

    body = payload.get("body")
    if isinstance(body, str):
        body = body.strip() or None

    data_field = payload.get("data")
    # allow stringified JSON
    if isinstance(data_field, str):
        try:
            data_field = json.loads(data_field)
        except Exception:
            # keep as raw string
            pass

    topic = payload.get("topic")
    if isinstance(topic, str):
        topic = topic.strip() or None

    status = payload.get("status") or "draft"
    scheduled_at = payload.get("scheduled_at")
    send_now = bool(payload.get("send_now"))
    tokens_field = _normalize_notification_tokens(payload.get("tokens"))
    data_field, topic, tokens_field, _ = _prepare_notification_target(
        payload=payload,
        data_field=data_field,
        topic=topic,
        tokens_field=tokens_field,
        db=db,
        require_tokens=send_now,
    )

    # If send_now is true, default initial status to 'draft' before triggering FCM
    initial_status = "draft" if send_now else status

    repeat_daily = bool(payload.get("repeat_daily"))
    repeat_time: Optional[str] = None
    if repeat_daily:
        # Derive repeat_time from scheduled_at if not provided explicitly
        raw_repeat_time = payload.get("repeat_time")
        if raw_repeat_time and isinstance(raw_repeat_time, str) and len(raw_repeat_time) == 5:
            repeat_time = raw_repeat_time
        elif scheduled_at:
            try:
                s = str(scheduled_at).rstrip("Z")
                dt = datetime.fromisoformat(s)
                repeat_time = dt.strftime("%H:%M")
            except Exception:
                pass

    nid = db.create_notification(
        title=title,
        body=body,
        data=data_field,
        topic=topic,
        tokens=tokens_field,
        status=initial_status,
        scheduled_at=scheduled_at,
        repeat_daily=repeat_daily,
        repeat_time=repeat_time,
    )

    if not nid:
        raise HTTPException(status_code=500, detail="Failed to create notification")

    sent_success = False
    fcm_response = None
    if send_now:
        fcm_data = _stringify_fcm_data(data_field)
        try:
            fcm_response = send_notification(
                title=title,
                body=body or "",
                data=fcm_data,
                topic=topic,
                tokens=tokens_field
            )
            db.mark_notification_sent(nid)
            sent_success = True
        except Exception as e:
            print(f"Error sending immediate notification for id {nid}: {e}")
            db.mark_notification_failed(nid)
            raise HTTPException(status_code=500, detail=f"Notification created (ID: {nid}), but failed to send: {str(e)}")

        return {"id": nid, "sent": sent_success, "response": fcm_response}

    return {"id": nid}


@app.post("/admin/notifications/{notification_id}/send", dependencies=[Depends(require_monitoring_access)])
def admin_send_notification(notification_id: int, db=Depends(get_db_connection)):
    n = db.get_notification_by_id(notification_id)
    if not n:
        raise HTTPException(status_code=404, detail="Notification not found")
    
    title = n.get("title")
    body = n.get("body") or ""
    data = n.get("data")
    topic = n.get("topic")
    tokens = n.get("tokens")
    _, topic, tokens, target_user_id = _prepare_notification_target(
        payload={},
        data_field=data,
        topic=topic,
        tokens_field=_normalize_notification_tokens(tokens),
        db=db,
        require_tokens=False,
    )
    if target_user_id and not tokens:
        raise HTTPException(
            status_code=400,
            detail="User ini belum punya token notifikasi. Login dari aplikasi mobile dulu atau simpan FCM token user.",
        )

    fcm_data = _stringify_fcm_data(data)

    try:
        response = send_notification(
            title=title,
            body=body,
            data=fcm_data,
            topic=topic,
            tokens=tokens
        )
        db.mark_notification_sent(notification_id)
        return {"status": "sent", "response": response}
    except Exception as e:
        print(f"FCM Notification sending failed for id {notification_id}: {e}")
        db.mark_notification_failed(notification_id)
        raise HTTPException(status_code=500, detail=f"Failed to send notification: {str(e)}")


@app.post("/admin/notifications/{notification_id}/mark-sent", dependencies=[Depends(require_monitoring_access)])
def admin_mark_notification_sent(notification_id: int, db=Depends(get_db_connection)):
    ok = db.mark_notification_sent(notification_id)
    if not ok:
        raise HTTPException(status_code=500, detail="Failed to mark notification as sent")
    return {"status": "sent"}


@app.put("/admin/notifications/{notification_id}", dependencies=[Depends(require_monitoring_access)])
def admin_update_notification(notification_id: int, payload: dict, db=Depends(get_db_connection)):
    n = db.get_notification_by_id(notification_id)
    if not n:
        raise HTTPException(status_code=404, detail="Notification not found")

    title = str(payload.get("title") or "").strip()
    if not title:
        raise HTTPException(status_code=400, detail="title is required")

    body = payload.get("body")
    if isinstance(body, str):
        body = body.strip() or None

    data_field = payload.get("data")
    if isinstance(data_field, str):
        try:
            data_field = json.loads(data_field)
        except Exception:
            pass

    topic = payload.get("topic")
    if isinstance(topic, str):
        topic = topic.strip() or None

    status = payload.get("status") or n.get("status") or "draft"
    scheduled_at = payload.get("scheduled_at")
    send_now = bool(payload.get("send_now"))
    tokens_field = _normalize_notification_tokens(payload.get("tokens"))
    data_field, topic, tokens_field, _ = _prepare_notification_target(
        payload=payload,
        data_field=data_field,
        topic=topic,
        tokens_field=tokens_field,
        db=db,
        require_tokens=send_now,
    )

    if send_now:
        status = "draft"

    repeat_daily = bool(payload.get("repeat_daily"))
    repeat_time: Optional[str] = None
    if repeat_daily:
        raw_repeat_time = payload.get("repeat_time")
        if raw_repeat_time and isinstance(raw_repeat_time, str) and len(raw_repeat_time) == 5:
            repeat_time = raw_repeat_time
        elif scheduled_at:
            try:
                s = str(scheduled_at).rstrip("Z")
                dt = datetime.fromisoformat(s)
                repeat_time = dt.strftime("%H:%M")
            except Exception:
                pass

    ok = db.update_notification(
        notification_id=notification_id,
        title=title,
        body=body,
        data=data_field,
        topic=topic,
        tokens=tokens_field,
        status=status,
        scheduled_at=scheduled_at,
        repeat_daily=repeat_daily,
        repeat_time=repeat_time,
    )

    if not ok:
        raise HTTPException(status_code=500, detail="Failed to update notification")

    sent_success = False
    fcm_response = None
    if send_now:
        fcm_data = _stringify_fcm_data(data_field)
        try:
            fcm_response = send_notification(
                title=title,
                body=body or "",
                data=fcm_data,
                topic=topic,
                tokens=tokens_field
            )
            db.mark_notification_sent(notification_id)
            sent_success = True
        except Exception as e:
            print(f"Error sending updated notification for id {notification_id}: {e}")
            db.mark_notification_failed(notification_id)
            raise HTTPException(status_code=500, detail=f"Notification updated, but failed to send: {str(e)}")

        return {"id": notification_id, "sent": sent_success, "response": fcm_response}

    return {"id": notification_id}


@app.delete("/admin/notifications/{notification_id}", dependencies=[Depends(require_monitoring_access)])
def admin_delete_notification(notification_id: int, db=Depends(get_db_connection)):
    n = db.get_notification_by_id(notification_id)
    if not n:
        raise HTTPException(status_code=404, detail="Notification not found")
    ok = db.delete_notification(notification_id)
    if not ok:
        raise HTTPException(status_code=500, detail="Failed to delete notification")
    return {"status": "deleted"}


# --- API compatibility aliases for frontend proxy prefix `/api/dermify` ---
@app.get("/api/dermify/admin/notifications", dependencies=[Depends(require_monitoring_access)])
def alias_list_notifications(limit: int = Query(default=50, ge=1, le=500), offset: int = Query(default=0, ge=0), db=Depends(get_db_connection)):
    return {"items": db.get_notifications(limit=limit, offset=offset)}


@app.get("/api/dermify/admin/notifications/{notification_id}", dependencies=[Depends(require_monitoring_access)])
def alias_get_notification(notification_id: int, db=Depends(get_db_connection)):
    n = db.get_notification_by_id(notification_id)
    if not n:
        raise HTTPException(status_code=404, detail="Notification not found")
    return n


@app.post("/api/dermify/admin/notifications", dependencies=[Depends(require_monitoring_access)])
def alias_create_notification(payload: dict, db=Depends(get_db_connection)):
    return admin_create_notification(payload, db)


@app.post("/api/dermify/admin/notifications/{notification_id}/send", dependencies=[Depends(require_monitoring_access)])
def alias_send_notification(notification_id: int, db=Depends(get_db_connection)):
    return admin_send_notification(notification_id, db)


@app.post("/api/dermify/admin/notifications/{notification_id}/mark-sent", dependencies=[Depends(require_monitoring_access)])
def alias_mark_notification_sent(notification_id: int, db=Depends(get_db_connection)):
    return admin_mark_notification_sent(notification_id, db)


@app.put("/api/dermify/admin/notifications/{notification_id}", dependencies=[Depends(require_monitoring_access)])
def alias_update_notification(notification_id: int, payload: dict, db=Depends(get_db_connection)):
    return admin_update_notification(notification_id, payload, db)


@app.delete("/api/dermify/admin/notifications/{notification_id}", dependencies=[Depends(require_monitoring_access)])
def alias_delete_notification(notification_id: int, db=Depends(get_db_connection)):
    return admin_delete_notification(notification_id, db)

@app.get("/history")
def get_user_history(request: Request, db=Depends(get_db_connection)):
    auth_header = request.headers.get("authorization")
    if not auth_header or not auth_header.lower().startswith("bearer "):
        raise HTTPException(status_code=401, detail="Missing or invalid Authorization header")
    token = auth_header.split(" ")[1]
    try:
        payload = jwt.decode(token, SECRET_KEY, algorithms=[ALGORITHM])
        user_email = payload.get("sub")
        if not user_email:
            raise HTTPException(status_code=401, detail="Invalid token")
    except JWTError as e:
        raise HTTPException(status_code=401, detail=f"Token error: {str(e)}")

    with db.engine.connect() as conn:
        user = conn.execute(
            text("SELECT id FROM users WHERE email = :email"),
            {"email": user_email}
        ).fetchone()
        if not user:
            raise HTTPException(status_code=404, detail="User not found")
        user_id = user.id if hasattr(user, 'id') else user[0]

        # QUERY DIPERBARUI: Melakukan JOIN agar data Product dan Analysis ikut terambil
        histories = conn.execute(
            text("""
                SELECT 
                    uh.id AS history_id,
                    uh.viewed_at,
                    a.id AS analysis_id,
                    a.summary,
                    a.recommendation,
                    a.status,
                    a.created_at,
                    p.name AS product_name,
                    p.brand AS product_brand,
                    p.category AS product_category,
                    s.image_url
                FROM user_histories uh
                JOIN analyses a ON uh.analysis_id = a.id
                JOIN scans s ON a.scan_id = s.id
                LEFT JOIN products p ON s.product_id = p.id
                WHERE uh.user_id = :user_id
                ORDER BY uh.viewed_at DESC
            """),
            {"user_id": user_id}
        ).fetchall()
        
        # Convert SQLAlchemy RowProxy/Row to dict
        result = []
        for row in histories:
            result.append(dict(row._mapping) if hasattr(row, '_mapping') else dict(row))
            
        return {"items": result}


if __name__ == "__main__":
    import uvicorn
    print("Starting FastAPI Backend Server via Uvicorn (Port 8000)...")
    uvicorn.run("main:app", host="0.0.0.0", port=8000, reload=True)
