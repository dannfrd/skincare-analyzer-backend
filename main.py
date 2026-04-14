from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from fastapi import Depends, FastAPI, File, Header, HTTPException, Query, UploadFile
from pydantic import BaseModel, Field
import shutil
import os

from modules.text_cleaning import clean_text_pipeline
from modules.ingredient_matching import match_tokens_to_db
from modules.gemini_ai import analyze_ingredients_with_ai
from database.db_connection import get_db_connection
from modules.preprocessing import preprocess_image
from modules.ocr import extract_text_from_image

API_MONITORING_KEY = os.getenv("MONITORING_API_KEY")

app = FastAPI()

# Make sure uploads directory exists
os.makedirs("uploads", exist_ok=True)

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
    # 1. Text cleaning
    cleaned_tokens = clean_text_pipeline(raw_text)
    
    # 2. Persiapkan database connection & data ingredients dari MySQL
    db = get_db_connection()
    db_ingredients = db.get_all_ingredients()
    
    # 3. Ingredient matching
    matched_ingredients = match_tokens_to_db(cleaned_tokens, db_ingredients)
    
    # 4. Gemini AI analysis
    ai_result_text = analyze_ingredients_with_ai(raw_text)

    # Membentuk dictionary final (JSON Result -> Flutter)
    result_data = {
        "input_text": raw_text,
        "cleaned_tokens": cleaned_tokens,
        "matched_ingredients": matched_ingredients,
        "ai_analysis": ai_result_text
    }

    # 5. MySQL Database (Laragon) - Simpan hasil analisis
    # Note: DB schema must align
    saved_id = db.save_analysis_result(raw_text=raw_text, ai_result=result_data)
    if saved_id:
        result_data["analysis_id"] = saved_id

    return result_data


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
