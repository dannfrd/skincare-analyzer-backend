from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from fastapi import Depends, FastAPI, File, Form, Header, HTTPException, Query, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi import Request
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field
import shutil
import os
from jose import jwt, JWTError
from dotenv import load_dotenv

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
from modules.preprocessing import preprocess_image
from modules.ocr import extract_text_from_image, extract_text_from_image_path
from modules.auth_api import router as auth_router
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
        from modules.embedding_utils import _get_model
        print("Pre-loading SentenceTransformer (embeddings)...")
        _get_model()
    except Exception as e:
        print(f"Error pre-loading SentenceTransformer: {e}")

    engine = os.getenv("OCR_ENGINE", "tesseract").lower().strip()
    if engine == "paddleocr":
        try:
            from modules.ocr import PaddleOCRProcessor
            print("Pre-loading PaddleOCR engine...")
            PaddleOCRProcessor.get_instance()
        except Exception as e:
            print(f"Error pre-loading PaddleOCR: {e}")
    else:
        print("Tesseract OCR murni aktif (tidak perlu pre-load model di memori).")
    print("="*50 + "\n")


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
        filename = f"user_{user_id}_{int(datetime.now().timestamp())}_{file.filename}"
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
                    password = COALESCE(NULLIF(:password, ''), password)
                WHERE id = :user_id
                """
            ), {
                "name": request_data.name or "",
                "email": request_data.email or "",
                "profile_picture": incoming_pp or "",
                "password": request_data.password or "",
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
    analysis_count: int = 0
    last_analysis_at: Optional[str] = None
    created_at: Optional[str] = None


class ProductSummaryResponse(BaseModel):
    id: int
    name: Optional[str] = None
    brand: Optional[str] = None
    category: Optional[str] = None
    barcode: Optional[str] = None
    scan_count: int = 0
    analysis_count: int = 0
    created_at: Optional[str] = None


class IngredientSummaryResponse(BaseModel):
    id: int
    name: Optional[str] = None
    function: Optional[str] = None
    risk_level: Optional[str] = None
    usage_count: int = 0
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
    analysis_created_at: Optional[str] = None
    viewed_at: Optional[str] = None

@app.get("/")
def root():
    return {"message": "Skincare Analyzer Backend Running"}

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
        # Save temporary file
        temp_path = f"uploads/{file.filename}"
        with open(temp_path, "wb") as buffer:
            shutil.copyfileobj(file.file, buffer)
        
        # 1. OCR Preprocessing and Extraction (routes to PaddleOCR if configured, otherwise falls back to Tesseract)
        extracted_text = extract_text_from_image_path(temp_path)
        
        # Cleanup temp file
        if os.path.exists(temp_path):
            os.remove(temp_path)
            
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
        )
        
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

def process_text_analysis(
    raw_text: str,
    user_id: Optional[int] = None,
    product_name: Optional[str] = None,
    product_brand: Optional[str] = None,
    product_category: Optional[str] = None,
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
    
    # 5. Enrich matched ingredients with dataset descriptions
    # Tambahkan deskripsi singkat dari dataset RAG untuk setiap ingredient
    for ingredient in matched_ingredients:
        ingredient_name = ingredient.get("name", "")
        dataset_info = get_ingredient_simple_description(ingredient_name)
        
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

    # Mapped simple descriptions
    for ing in matched_ingredients:
        name = str(ing.get("name") or ing.get("ocr_token_used") or "").upper().strip()
        if name in simple_descriptions_map:
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
):
    """
    Return top-N similar products from the INCIDecoder dataset.

    Strategy options (mode param):
    - 'auto'     : Qdrant semantic search first, falls back to string-overlap
                   when fewer than 3 semantic results are found.
    - 'semantic' : Pure Qdrant vector similarity (requires Qdrant data to be
                   set up via qdrant_setup.py).
    - 'overlap'  : Classic substring-overlap (fast, no Qdrant required).

    Response fields per product:
      name, brand, category_tags, url, similarity_pct, matched_ingredients,
      match_reason (e.g. "Fungsi serupa: moisturizer, humectant")
    """
    ingredient_names = [i.strip() for i in ingredients.split(",") if i.strip()]
    if not ingredient_names:
        return {"recommendations": [], "mode_used": mode}

    valid_modes = {"auto", "semantic", "overlap"}
    if mode not in valid_modes:
        mode = "auto"

    result = _recommender_get(ingredient_names, limit=limit, mode=mode, category=category)
    return {"recommendations": result, "mode_used": mode}


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

    def _run_ingest():
        _set_ingesting(True)
        try:
            print("[reingest] Starting Qdrant re-ingestion...")
            setup_qdrant()
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
    limit: int = Query(default=200, ge=1, le=500),
    _: None = Depends(require_monitoring_access),
):
    db = get_db_connection()
    return db.get_users(limit=limit)


@app.get("/metrics/analyses", response_model=List[RecentAnalysisResponse])
def metrics_analyses(
    limit: int = Query(default=200, ge=1, le=500),
    _: None = Depends(require_monitoring_access),
):
    db = get_db_connection()
    return db.get_analyses(limit=limit)


@app.get("/metrics/analysis-details", response_model=List[AnalysisDetailSummaryResponse])
def metrics_analysis_details(
    limit: int = Query(default=200, ge=1, le=500),
    _: None = Depends(require_monitoring_access),
):
    db = get_db_connection()
    return db.get_analysis_details(limit=limit)


@app.get("/metrics/products", response_model=List[ProductSummaryResponse])
def metrics_products(
    limit: int = Query(default=200, ge=1, le=500),
    _: None = Depends(require_monitoring_access),
):
    db = get_db_connection()
    return db.get_products(limit=limit)


@app.get("/metrics/ingredients", response_model=List[IngredientSummaryResponse])
def metrics_ingredients(
    limit: int = Query(default=200, ge=1, le=500),
    _: None = Depends(require_monitoring_access),
):
    db = get_db_connection()
    return db.get_ingredients(limit=limit)


@app.get("/metrics/user-histories", response_model=List[UserHistorySummaryResponse])
def metrics_user_histories(
    limit: int = Query(default=200, ge=1, le=500),
    _: None = Depends(require_monitoring_access),
):
    db = get_db_connection()
    return db.get_user_histories(limit=limit)

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
                    p.category AS product_category
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
