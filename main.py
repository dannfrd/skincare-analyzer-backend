from fastapi import FastAPI, UploadFile, File, HTTPException
from pydantic import BaseModel
import shutil
import os

from modules.text_cleaning import clean_text_pipeline
from modules.ingredient_matching import match_tokens_to_db
from modules.gemini_ai import analyze_ingredients_with_ai
from database.db_connection import get_db_connection
from modules.preprocessing import preprocess_image
from modules.ocr import extract_text_from_image

app = FastAPI()

# Make sure uploads directory exists
os.makedirs("uploads", exist_ok=True)

# model request dari Flutter
class IngredientRequest(BaseModel):
    text: str

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
