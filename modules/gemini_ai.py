import os
import threading
import warnings
import importlib
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
    defaults = ["gemini-2.5-flash", "gemini-2.0-flash", "gemini-1.5-flash"]

    candidates = [GEMINI_MODEL] + configured + defaults
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
Anda adalah analis ingredient skincare yang harus ketat berbasis konteks.

ATURAN WAJIB:
1. Bahas hanya ingredient yang ada pada daftar ingredient OCR di bawah.
2. Jangan menambah ingredient yang tidak disebutkan.
3. Jika data ingredient tidak ada pada konteks, tulis jelas: "tidak ada data pada dataset".
4. Hindari klaim berlebihan, diagnosis medis, atau saran yang di luar data.
5. Jawab singkat, terstruktur, dan praktis dalam Bahasa Indonesia.

Daftar ingredient hasil OCR (trusted input):
{ingredient_list_text}

Status RAG: {rag_status}

Konteks tepercaya (gunakan ini sebagai sumber utama):
{trusted_context}

FORMAT JAWABAN:
1) Ingredients terdeteksi
2) Safety level keseluruhan (safe / moderate / risky) + alasan singkat
3) Ingredient yang perlu diperhatikan (jika ada)
4) Ingredient yang cenderung aman (jika ada)
5) Batasan analisis (apa yang tidak ada datanya)
""".strip()


def _call_gemini(prompt: str) -> Dict[str, Any]:
    model_errors: List[str] = []

    for model in _model_candidates():
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
                    "models_tried": [attempt.split(":", 1)[0] for attempt in model_errors] + [model],
                }
            model_errors.append(f"{model}: empty response")
        except Exception as exc:
            if _is_auth_error(exc):
                raise RuntimeError("GEMINI_API_KEY tidak valid atau tidak punya izin akses model.") from exc

            model_errors.append(f"{model}: {exc}")
            if _is_non_retryable_request_error(exc):
                break

    raise RuntimeError(
        "Semua kandidat model Gemini gagal. "
        f"Detail: {' || '.join(model_errors)}"
    )


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
        failure_message = (
            "Analisis AI gagal: "
            f"{error_holder['value']}. Ringkasan rule-based tetap digunakan."
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