import os
import threading
from dotenv import load_dotenv
from google import genai

load_dotenv()

API_KEY = os.getenv("GEMINI_API_KEY")
GEMINI_MODEL = os.getenv("GEMINI_MODEL", "gemini-2.5-flash")
GEMINI_TIMEOUT_SECONDS = int(os.getenv("GEMINI_TIMEOUT_SECONDS", "30"))

client = genai.Client(api_key=API_KEY) if API_KEY else None


def _build_prompt(text: str) -> str:
    return f"""
You are a skincare ingredient expert.

Analyze the following skincare ingredients:

{text}

Return:
1. list of ingredients detected
2. safety level (safe / moderate / risky)
3. explanation
"""


def _call_gemini(prompt: str) -> str:
    response = client.models.generate_content(
        model=GEMINI_MODEL,
        contents=prompt,
    )
    return (response.text or "").strip()


def analyze_ingredients_with_ai(text):
    cleaned_text = (text or "").strip()
    if not cleaned_text:
        return "Teks kosong. Analisis AI dilewati."

    if client is None:
        return "Analisis AI dilewati karena GEMINI_API_KEY belum dikonfigurasi."

    prompt = _build_prompt(cleaned_text)
    result_holder = {"value": ""}
    error_holder = {"value": None}

    def run_request() -> None:
        try:
            result_holder["value"] = _call_gemini(prompt)
        except Exception as exc:  # pragma: no cover - defensive fallback
            error_holder["value"] = exc

    request_thread = threading.Thread(target=run_request, daemon=True)
    request_thread.start()
    request_thread.join(timeout=GEMINI_TIMEOUT_SECONDS)

    if request_thread.is_alive():
        return (
            f"Analisis AI timeout lebih dari {GEMINI_TIMEOUT_SECONDS} detik. "
            "Ringkasan rule-based tetap digunakan."
        )

    if error_holder["value"] is not None:
        return (
            "Analisis AI gagal: "
            f"{error_holder['value']}. Ringkasan rule-based tetap digunakan."
        )

    ai_text = (result_holder["value"] or "").strip()
    if not ai_text:
        return "Analisis AI kosong. Ringkasan rule-based tetap digunakan."

    return ai_text