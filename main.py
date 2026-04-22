from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from fastapi import Depends, FastAPI, File, Header, HTTPException, Query, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi import Request
from pydantic import BaseModel, Field
import shutil
import os
from jose import jwt, JWTError

SECRET_KEY = os.getenv("SECRET_KEY", "secret")
ALGORITHM = "HS256"

from modules.text_cleaning import clean_text_pipeline, extract_ingredient_text
from modules.ingredient_matching import match_tokens_to_db
from modules.gemini_ai import analyze_ingredients_with_ai
from modules.expert_system import run_expert_system
from database.db_connection import get_db_connection
from modules.preprocessing import preprocess_image
from modules.ocr import extract_text_from_image
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

# Make sure uploads directory exists
os.makedirs("uploads", exist_ok=True)


app.include_router(auth_router)

# model request untuk save history
class SaveHistoryRequest(BaseModel):
    analysis_id: int


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

    with db.engine.connect() as conn:
        user = conn.execute(
            text("SELECT id FROM users WHERE email = :email"),
            {"email": user_email}
        ).fetchone()
        if not user:
            raise HTTPException(status_code=404, detail="User not found")
        user_id = user.id if hasattr(user, 'id') else user[0]

        # Cek apakah analysis_id valid

        analysis = conn.execute(
            text("SELECT id FROM analyses WHERE id = :analysis_id"),
            {"analysis_id": request_data.analysis_id}
        ).fetchone()
        if not analysis:
            raise HTTPException(status_code=404, detail="Analysis ID not found in analyses table")

        # Hindari duplikasi save untuk analysis yang sama
        existing = conn.execute(
            text("""
                SELECT id FROM user_histories
                WHERE user_id = :user_id AND analysis_id = :analysis_id
                LIMIT 1
            """),
            {"user_id": user_id, "analysis_id": request_data.analysis_id}
        ).fetchone()
        if existing:
            return {"message": "Analisis sudah ada di histori."}

        # Simpan ke tabel user_histories
        save_query = text("""
            INSERT INTO user_histories (user_id, analysis_id)
            VALUES (:user_id, :analysis_id)
        """)
        conn.execute(save_query, {"user_id": user_id, "analysis_id": request_data.analysis_id})
        conn.commit()

    return {"message": "Daftar histori telah berhasil ditambahkan."}

# model request dari Flutter
class IngredientRequest(BaseModel):
    text: str


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

@app.get("/")
def root():
    return {"message": "Skincare Analyzer Backend Running"}

@app.post("/analyze")
def analyze_ingredients(data: IngredientRequest):
    raw_text = data.text
    return process_text_analysis(raw_text)


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
async def analyze_image(file: UploadFile = File(...)):
    """Receives an image for OCR, then processes the text."""
    try:
        # Save temporary file
        temp_path = f"uploads/{file.filename}"
        with open(temp_path, "wb") as buffer:
            shutil.copyfileobj(file.file, buffer)
        
        # 1. OCR Preprocessing and Extraction
        processed_image = preprocess_image(temp_path)
        extracted_text = extract_text_from_image(processed_image)
        
        # Cleanup temp file
        if os.path.exists(temp_path):
            os.remove(temp_path)
            
        if not extracted_text.strip():
            raise HTTPException(status_code=400, detail="Could not extract text from the image.")
            
        # 2. Process text through the existing pipeline
        return process_text_analysis(extracted_text)
        
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

def process_text_analysis(raw_text: str):
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

    # 5. Rule-based expert analysis
    expert_report = run_expert_system(matched_ingredients)
    
    # 6. Gemini AI analysis with model fallback + dataset-grounded prompt
    ai_result_payload = analyze_ingredients_with_ai(
        text=ingredient_text,
        ingredient_tokens=cleaned_tokens,
        matched_ingredients=matched_ingredients,
        include_metadata=True,
    )

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

    # 7. MySQL Database (Laragon) - Simpan hasil analisis
    # Note: DB schema must align
    saved_id = db.save_analysis_result(
        raw_text=raw_text,
        ai_result=result_data,
        matched_ingredients=matched_ingredients,
        expert_report=expert_report,
    )
    if saved_id:
        result_data["analysis_id"] = saved_id

    return result_data


def _build_summary_text(expert_report: Dict[str, Any]) -> str:
    score = expert_report.get("overall_score", 0)
    classification = expert_report.get("classification", "Unknown")
    total_identified = expert_report.get("total_ingredients_identified", 0)
    warning_count = expert_report.get("warnings_found", 0)
    return (
        f"Skor keamanan {score}/100 ({classification}). "
        f"Bahan dikenali: {total_identified}. Peringatan: {warning_count}."
    )


def _build_recommendation_text(expert_report: Dict[str, Any], ai_text: str) -> str:
    flags = expert_report.get("flags") if isinstance(expert_report, dict) else []
    if isinstance(flags, list) and flags:
        first_flag = flags[0] if isinstance(flags[0], dict) else {}
        ingredient = first_flag.get("ingredient")
        message = first_flag.get("message")
        if ingredient and message:
            return f"Perhatikan ingredient {ingredient}: {message}"

    unknown_count = expert_report.get("total_unknown", 0) if isinstance(expert_report, dict) else 0
    if isinstance(unknown_count, int) and unknown_count > 0:
        return (
            f"Ada {unknown_count} bahan yang belum dikenali. "
            "Lengkapi master ingredients agar analisis lebih akurat."
        )

    cleaned_ai = (ai_text or "").strip()
    if cleaned_ai:
        return cleaned_ai[:260]

    return "Secara umum formula cukup aman, tetap lakukan patch test sebelum pemakaian rutin."


def require_monitoring_api_key(x_api_key: str | None = Header(default=None)):
    """Simple API key guard for monitoring endpoints."""
    if API_MONITORING_KEY and x_api_key != API_MONITORING_KEY:
        raise HTTPException(status_code=401, detail="Unauthorized")


def _current_timestamp() -> datetime:
    return datetime.now(timezone.utc)


def _service_status(healthy: bool, detail: str = "") -> Dict[str, Any]:
    return {
        "status": "up" if healthy else "down",
        "detail": detail,
    }


@app.get("/health", response_model=HealthResponse)
def health_status(_: None = Depends(require_monitoring_api_key)):
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
def metrics_summary(_: None = Depends(require_monitoring_api_key)):
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
    _: None = Depends(require_monitoring_api_key),
):
    db = get_db_connection()
    records = db.get_recent_analysis_results(limit=limit)
    # FastAPI will coerce dict list into the response model
    return records

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
    except JWTError:
        raise HTTPException(status_code=401, detail="Invalid token")

    with db.engine.connect() as conn:
        user = conn.execute(
            text("SELECT id FROM users WHERE email = :email"),
            {"email": user_email}
        ).fetchone()
        if not user:
            raise HTTPException(status_code=404, detail="User not found")

        user_id = user.id if hasattr(user, 'id') else user[0]

        # History diambil dari user_histories karena tombol "Simpan Hasil" menyimpan analysis_id ke tabel ini.
        results = conn.execute(
            text("""
                SELECT
                    uh.id AS history_id,
                    uh.viewed_at,
                    a.id AS analysis_id,
                    a.summary,
                    a.recommendation,
                    a.status,
                    a.created_at AS analysis_created_at,
                    s.id AS scan_id,
                    p.id AS product_id,
                    p.name AS product_name,
                    p.brand AS product_brand,
                    GROUP_CONCAT(DISTINCT i.risk_level ORDER BY i.risk_level SEPARATOR ',') AS risk_levels
                FROM user_histories uh
                INNER JOIN analyses a ON a.id = uh.analysis_id
                LEFT JOIN scans s ON s.id = a.scan_id
                LEFT JOIN products p ON p.id = s.product_id
                LEFT JOIN scan_ingredients si ON si.scan_id = s.id
                LEFT JOIN ingredients i ON i.id = si.ingredient_id
                WHERE uh.user_id = :user_id
                GROUP BY
                    uh.id,
                    uh.viewed_at,
                    a.id,
                    a.summary,
                    a.recommendation,
                    a.status,
                    a.created_at,
                    s.id,
                    p.id,
                    p.name,
                    p.brand
                ORDER BY COALESCE(uh.viewed_at, a.created_at) DESC
            """),
            {"user_id": user_id}
        ).mappings().all()

        payload: List[Dict[str, Any]] = []
        for row in results:
            created_at = row.get("viewed_at") or row.get("analysis_created_at")
            risk_level = _resolve_history_risk_level(row.get("risk_levels"))

            payload.append({
                "id": row.get("history_id"),
                "created_at": created_at.isoformat() if hasattr(created_at, "isoformat") else created_at,
                "analysis_id": row.get("analysis_id"),
                "product": {
                    "id": row.get("product_id"),
                    "name": row.get("product_name") or f"Analysis #{row.get('analysis_id')}",
                    "brand": row.get("product_brand") or "No Brand",
                },
                "analyses": [
                    {
                        "id": row.get("analysis_id"),
                        "summary": row.get("summary"),
                        "recommendation": row.get("recommendation"),
                        "status": row.get("status"),
                        "risk_level": risk_level,
                    }
                ],
            })

        return payload
