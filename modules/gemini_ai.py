import os
import threading
import warnings
import importlib
import json
import re
from typing import Any, Dict, List
from dotenv import load_dotenv

try:
    from google import genai as google_genai_sdk
except ImportError:
    google_genai_sdk = None

google_legacy_genai_sdk = None

from modules.rag_context import build_rag_context

load_dotenv()

API_KEY = os.getenv("GEMINI_API_KEY")
GEMINI_MODEL = os.getenv("GEMINI_MODEL", "gemini-2.5-flash")
GEMINI_TIMEOUT_SECONDS = int(os.getenv("GEMINI_TIMEOUT_SECONDS", "30"))
DEFAULT_MODEL_CANDIDATES = [
    "gemini-2.5-flash",
    "gemini-2.5-flash-lite",
    "gemini-3.1-flash-lite",
    "gemini-3.5-flash",
]


class GeminiFallbackError(RuntimeError):
    def __init__(self, models_tried: List[str], error_summaries: List[str]):
        self.models_tried = models_tried
        self.error_summaries = error_summaries
        models = ", ".join(models_tried) or "tidak ada"
        super().__init__(
            "Semua kandidat model Gemini sedang tidak tersedia atau kuotanya habis "
            f"(dicoba: {models}). Silakan coba lagi beberapa saat."
        )


def _load_legacy_sdk():
    global google_legacy_genai_sdk
    if google_legacy_genai_sdk is not None:
        return google_legacy_genai_sdk

    try:
        with warnings.catch_warnings():
            warnings.filterwarnings("ignore", category=FutureWarning, module=r"google\.generativeai")
            google_legacy_genai_sdk = importlib.import_module("google.generativeai")
        return google_legacy_genai_sdk
    except ImportError:
        return None

if API_KEY and google_genai_sdk is not None:
    client = google_genai_sdk.Client(api_key=API_KEY)
    GEMINI_SDK_MODE = "google-genai"
elif API_KEY:
    legacy_sdk = _load_legacy_sdk()
    if legacy_sdk is not None:
        legacy_sdk.configure(api_key=API_KEY)
        client = None
        GEMINI_SDK_MODE = "google-generativeai"
    else:
        client = None
        GEMINI_SDK_MODE = "unavailable"
else:
    client = None
    GEMINI_SDK_MODE = "unavailable"


def _extract_response_text(response: Any) -> str:
    try:
        text = getattr(response, "text", "")
    except Exception:
        text = ""
    return (text or "").strip() if isinstance(text, str) else ""


def _model_candidates() -> List[str]:
    configured = [item.strip() for item in os.getenv("GEMINI_MODEL_CANDIDATES", "").split(",") if item.strip()]

    candidates = [GEMINI_MODEL] + configured + DEFAULT_MODEL_CANDIDATES
    deduplicated: List[str] = []
    seen = set()
    for candidate in candidates:
        if candidate and candidate not in seen:
            deduplicated.append(candidate)
            seen.add(candidate)
    return deduplicated


def _error_text(exc: Exception) -> str:
    return f"{type(exc).__name__}: {exc}".lower()


def _is_auth_error(exc: Exception) -> bool:
    text = _error_text(exc)
    auth_markers = [
        "invalid api key",
        "api key not valid",
        "permission denied",
        "unauthorized",
        "forbidden",
        "insufficient authentication",
    ]
    return any(marker in text for marker in auth_markers)


def _is_non_retryable_request_error(exc: Exception) -> bool:
    text = _error_text(exc)
    non_retryable_markers = [
        "invalid argument",
        "400",
        "malformed",
        "failed precondition",
    ]
    return any(marker in text for marker in non_retryable_markers)


def _summarize_model_error(exc: Exception) -> str:
    text = _error_text(exc)
    if "429" in text or "resource_exhausted" in text or "quota" in text:
        return "kuota/rate limit habis"
    if "503" in text or "unavailable" in text or "high demand" in text:
        return "layanan sedang sibuk"
    if "404" in text or "not found" in text:
        return "model tidak tersedia"
    if "timeout" in text or "deadline" in text:
        return "request timeout"
    return "request gagal"


def _build_db_context(matched_ingredients: List[Dict[str, Any]] | None) -> str:
    if not matched_ingredients:
        return ""

    context_lines = []
    for ingredient in matched_ingredients:
        if str(ingredient.get("status") or "").lower() == "unknown":
            continue

        name = str(ingredient.get("name") or "").strip()
        if not name:
            continue

        details = []
        description = str(ingredient.get("description") or "").strip()
        if description:
            details.append(f"deskripsi: {description}")

        function = str(ingredient.get("function") or "").strip()
        if function:
            details.append(f"fungsi: {function}")

        comedogenic_rating = ingredient.get("comedogenic_rating")
        if isinstance(comedogenic_rating, int) and comedogenic_rating > 0:
            details.append(f"comedogenic_rating: {comedogenic_rating}/5")

        if bool(ingredient.get("is_allergen")):
            details.append("is_allergen: true")

        if bool(ingredient.get("unsafe_for_pregnancy")):
            details.append("unsafe_for_pregnancy: true")

        if details:
            context_lines.append(f"- {name}: {' | '.join(details)}")

        if len(context_lines) >= 15:
            break

    if not context_lines:
        return ""

    return "Database context (internal evidence):\n" + "\n".join(context_lines)


def _build_prompt(
    text: str,
    ingredient_tokens: List[str] | None = None,
    matched_ingredients: List[Dict[str, Any]] | None = None,
) -> str:
    tokens = [token.strip().upper() for token in (ingredient_tokens or []) if token and token.strip()]
    unique_tokens = list(dict.fromkeys(tokens))

    if not unique_tokens and text.strip():
        unique_tokens = [token.strip() for token in text.upper().split(",") if token.strip()]

    ingredient_list_text = ", ".join(unique_tokens) if unique_tokens else text.strip()

    rag_context, rag_meta = build_rag_context(unique_tokens)
    db_context = _build_db_context(matched_ingredients)
    rag_status = "enabled" if rag_context else f"disabled ({rag_meta.get('reason', 'unknown')})"

    trusted_context_blocks = []
    if rag_context:
        trusted_context_blocks.append(rag_context)
    if db_context:
        trusted_context_blocks.append(db_context)

    trusted_context = "\n\n".join(trusted_context_blocks)
    if not trusted_context:
        trusted_context = "Tidak ada konteks tambahan yang berhasil diambil dari dataset."

    return f"""
Anda adalah analis skincare profesional.

ATURAN WAJIB:
1. Bahas hanya ingredient yang ada pada daftar di bawah.
2. JANGAN menggunakan kategori "Safe" atau "Warning" (karena produk skincare di Indonesia umumnya sudah BPOM dan aman). Fokus pada KECOCOKAN.
3. Jelaskan juga secara singkat fungsi bahan-bahan yang belum dikenali di dataset agar awam paham.
4. Jika ada bahan yang tidak disarankan untuk kondisi tertentu (misal: ibu hamil, kulit sangat sensitif), sarankan pengguna untuk berkonsultasi dengan dokter/klinik.

Daftar ingredient hasil OCR (trusted input):
{ingredient_list_text}

Status RAG: {rag_status}

Konteks tepercaya (gunakan ini sebagai sumber utama):
{trusted_context}

FORMAT JAWABAN (Jawab dengan paragraf yang rapi dan mengalir):
1) Kecocokan Jenis Kulit: Produk ini cocok untuk jenis kulit apa dan kurang cocok untuk jenis kulit apa.
2) Kombinasi Bahan: Bahan ini cocok dikombinasi dengan apa, dan tidak cocok dikombinasi dengan apa.
3) Peringatan Khusus & Penjelasan Bahan: Jelaskan singkat jika ada bahan yang perlu dihindari ibu hamil/kondisi tertentu (sarankan ke dokter). Jelaskan fungsi bahan utama dan bahan yang mungkin kurang umum agar awam paham.
""".strip()


def _call_gemini(prompt: str) -> Dict[str, Any]:
    models_tried: List[str] = []
    error_summaries: List[str] = []

    for model in _model_candidates():
        models_tried.append(model)
        try:
            if GEMINI_SDK_MODE == "google-genai":
                response = client.models.generate_content(
                    model=model,
                    contents=prompt,
                )
            elif GEMINI_SDK_MODE == "google-generativeai":
                response = google_legacy_genai_sdk.GenerativeModel(model_name=model).generate_content(prompt)
            else:
                raise RuntimeError("SDK Gemini tidak tersedia. Install google-genai atau google-generativeai.")

            text = _extract_response_text(response)
            if text:
                return {
                    "text": text,
                    "model": model,
                    "models_tried": models_tried,
                }
            error_summaries.append(f"{model}: respons kosong")
        except Exception as exc:
            if _is_auth_error(exc):
                raise RuntimeError("GEMINI_API_KEY tidak valid atau tidak punya izin akses model.") from exc

            error_summaries.append(f"{model}: {_summarize_model_error(exc)}")
            if _is_non_retryable_request_error(exc):
                break

    raise GeminiFallbackError(models_tried, error_summaries)


def analyze_ingredients_with_ai(
    text: str,
    ingredient_tokens: List[str] | None = None,
    matched_ingredients: List[Dict[str, Any]] | None = None,
    include_metadata: bool = False,
):
    cleaned_text = (text or "").strip()
    cleaned_tokens = [token for token in (ingredient_tokens or []) if token and token.strip()]

    if not cleaned_text and not cleaned_tokens:
        return "Teks kosong. Analisis AI dilewati."

    if not API_KEY:
        return "Analisis AI dilewati karena GEMINI_API_KEY belum dikonfigurasi."

    if GEMINI_SDK_MODE == "unavailable":
        return "Analisis AI dilewati karena dependency Gemini belum terpasang (google-genai/google-generativeai)."

    prompt = _build_prompt(
        text=cleaned_text,
        ingredient_tokens=cleaned_tokens,
        matched_ingredients=matched_ingredients,
    )
    result_holder: Dict[str, Any] = {"value": "", "model": None, "models_tried": []}
    error_holder = {"value": None}

    def run_request() -> None:
        try:
            response_payload = _call_gemini(prompt)
            result_holder["value"] = response_payload.get("text") or ""
            result_holder["model"] = response_payload.get("model")
            result_holder["models_tried"] = response_payload.get("models_tried") or []
        except Exception as exc:  # pragma: no cover - defensive fallback
            error_holder["value"] = exc

    request_thread = threading.Thread(target=run_request, daemon=True)
    request_thread.start()
    request_thread.join(timeout=GEMINI_TIMEOUT_SECONDS)

    if request_thread.is_alive():
        timeout_message = (
            f"Analisis AI timeout lebih dari {GEMINI_TIMEOUT_SECONDS} detik. "
            "Ringkasan rule-based tetap digunakan."
        )
        if include_metadata:
            return {
                "text": timeout_message,
                "model": None,
                "models_tried": result_holder.get("models_tried") or [],
            }
        return timeout_message

    if error_holder["value"] is not None:
        request_error = error_holder["value"]
        models_tried = getattr(request_error, "models_tried", None)
        if models_tried:
            result_holder["models_tried"] = models_tried
        failure_message = (
            "Analisis AI gagal: "
            f"{request_error} Ringkasan rule-based tetap digunakan."
        )
        if include_metadata:
            return {
                "text": failure_message,
                "model": None,
                "models_tried": result_holder.get("models_tried") or [],
            }
        return failure_message

    ai_text = (result_holder["value"] or "").strip()
    if not ai_text:
        empty_message = "Analisis AI kosong. Ringkasan rule-based tetap digunakan."
        if include_metadata:
            return {
                "text": empty_message,
                "model": result_holder.get("model"),
                "models_tried": result_holder.get("models_tried") or [],
            }
        return empty_message

    if include_metadata:
        return {
            "text": ai_text,
            "model": result_holder.get("model"),
            "models_tried": result_holder.get("models_tried") or [],
        }

    return ai_text


def generate_simple_descriptions(matched_ingredients: List[Dict[str, Any]]) -> Dict[str, str]:
    if not API_KEY or GEMINI_SDK_MODE == "unavailable":
        return {}

    ingredient_list = []
    for ing in matched_ingredients:
        name = ing.get("name") or ing.get("ocr_token_used") or ""
        if not name:
            continue
        desc = ing.get("dataset_description") or ing.get("description") or ""
        funcs = ing.get("dataset_functions") or ing.get("function") or ""
        ingredient_list.append(f"- {name}: Data({desc}) Fungsi({funcs})")

    if not ingredient_list:
        return {}

    prompt = f"""
Anda adalah ahli skincare yang bertugas menjelaskan bahan skincare ke orang awam.
Berikan penjelasan SINGKAT (maksimal 1 kalimat, gunakan bahasa awam/mudah dipahami, JANGAN bahasa kimia rumit) tentang fungsi utama dari setiap bahan berikut.
Tujuan: Pembaca langsung tahu "bahan ini buat apa".
Jika datanya kosong/terbatas (misal AQUA), gunakan pengetahuan umum tentang bahan skincare tersebut (misal AQUA = Air murni yang berfungsi sebagai pelarut utama).

Daftar Bahan:
{chr(10).join(ingredient_list)}

FORMAT JAWABAN WAJIB JSON VALID (TANPA teks lain):
{{
  "NAMA_BAHAN": "Penjelasan singkat maksimal 1 kalimat...",
  "NAMA_BAHAN_2": "..."
}}
""".strip()

    result_holder = {"value": {}}

    def run_request() -> None:
        try:
            response_payload = _call_gemini(prompt)
            text = response_payload.get("text", "").strip()
            
            # Clean up markdown JSON block if present
            if text.startswith("```json"):
                text = text[7:]
            if text.startswith("```"):
                text = text[3:]
            if text.endswith("```"):
                text = text[:-3]
                
            text = text.strip()
            result_holder["value"] = json.loads(text)
        except Exception as exc:
            print(f"Error generating simple descriptions: {exc}")

    request_thread = threading.Thread(target=run_request, daemon=True)
    request_thread.start()
    request_thread.join(timeout=GEMINI_TIMEOUT_SECONDS)

    # Normalize keys to uppercase for easier matching later
    raw_dict = result_holder["value"]
    if isinstance(raw_dict, dict):
        return {str(k).upper().strip(): str(v) for k, v in raw_dict.items()}
    return {}


def extract_ingredients_from_ocr(raw_text: str) -> List[str]:
    """
    Uses Gemini AI to intelligently extract ONLY the ingredients list from messy OCR text.
    Ignores marketing fluff, directions, and warnings.
    Returns a clean list of individual ingredient names.
    """
    if not API_KEY or GEMINI_SDK_MODE == "unavailable":
        return []

    if not raw_text or not raw_text.strip():
        return []

    prompt = f"""
Anda adalah sistem pengekstrak data (Data Extractor) yang ahli dalam mengidentifikasi bahan/komposisi (ingredients) kosmetik dari teks hasil pemindaian OCR.

Teks di bawah ini adalah hasil OCR dari kemasan suatu produk. Teks ini sangat berantakan dan mungkin memuat campuran antara instruksi pemakaian, peringatan, nama pabrik, dan daftar komposisi (ingredients).

TUGAS ANDA:
1. Temukan bagian yang berisi daftar "Ingredients" atau "Komposisi".
2. Ekstrak HANYA nama-nama bahan tersebut.
3. ABAIKAN teks lain seperti "Cara pakai", "Peringatan", "Netto", alamat pabrik, nomor BPOM, atau deskripsi produk.
4. Jangan menambahkan nomor atau bullet point.

TEKS OCR MENTAH:
\"\"\"
{raw_text.strip()}
\"\"\"

FORMAT JAWABAN WAJIB JSON ARRAY BERISI STRING (TANPA teks lain di luar JSON):
[
  "WATER",
  "GLYCERIN",
  "NIACINAMIDE"
]
""".strip()

    result_holder = {"value": []}

    def run_request() -> None:
        try:
            response_payload = _call_gemini(prompt)
            text = response_payload.get("text", "").strip()
            
            # Clean up markdown JSON block if present
            if text.startswith("```json"):
                text = text[7:]
            if text.startswith("```"):
                text = text[3:]
            if text.endswith("```"):
                text = text[:-3]
                
            text = text.strip()
            parsed = json.loads(text)
            
            if isinstance(parsed, list):
                result_holder["value"] = [str(item).strip().upper() for item in parsed if str(item).strip()]
        except Exception as exc:
            print(f"Error extracting ingredients via AI: {exc}")

    request_thread = threading.Thread(target=run_request, daemon=True)
    request_thread.start()
    request_thread.join(timeout=GEMINI_TIMEOUT_SECONDS)

    return result_holder["value"]
