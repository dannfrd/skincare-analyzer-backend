"""
ocr.py - OCR Module (PaddleOCR) — Optimized for VPS 2GB RAM

Strategi optimasi:
  1. use_angle_cls=True dipertahankan (foto bisa miring)
  2. det_limit_side_len=480  — kurangi resolusi internal detection model
  3. cpu_threads=2           — manfaatkan multi-core VPS
  4. show_log=False          — matikan log verbose PaddlePaddle
  5. Image MD5 hash cache    — hasil OCR di-cache per gambar unik (max 50 entri)
  6. Gambar BGR langsung     — tidak perlu konversi bolak-balik grayscale
"""

import os
# Fix internal PaddlePaddle CPU bugs by disabling PIR and MKLDNN globally
os.environ['FLAGS_enable_pir_api'] = '0'
os.environ['FLAGS_use_mkldnn'] = '0'
# Kurangi log verbose PaddlePaddle agar tidak memperlambat I/O
os.environ['GLOG_minloglevel'] = '3'

import hashlib
import numpy as np
import logging
import cv2
from collections import OrderedDict

logger = logging.getLogger(__name__)

# ─────────────────────────────────────────────────────────────
# Singleton OCR instance — di-load SEKALI, digunakan selamanya
# ─────────────────────────────────────────────────────────────
paddle_ocr_instance = None

# ─────────────────────────────────────────────────────────────
# LRU Cache: MD5(image bytes) → hasil teks
# Max 50 entri agar tidak memakan RAM di VPS 2GB
# ─────────────────────────────────────────────────────────────
_MAX_CACHE_SIZE = 50
_ocr_cache: OrderedDict = OrderedDict()  # {md5_hex: str}


def _image_hash(image: np.ndarray) -> str:
    """MD5 hash dari raw bytes gambar — dipakai sebagai cache key."""
    return hashlib.md5(image.tobytes()).hexdigest()


def _cache_get(key: str):
    """Ambil dari cache, pindahkan ke akhir (LRU)."""
    if key in _ocr_cache:
        _ocr_cache.move_to_end(key)
        return _ocr_cache[key]
    return None


def _cache_put(key: str, value: str):
    """Simpan ke cache. Hapus entri terlama jika sudah penuh."""
    _ocr_cache[key] = value
    _ocr_cache.move_to_end(key)
    if len(_ocr_cache) > _MAX_CACHE_SIZE:
        _ocr_cache.popitem(last=False)  # hapus yang paling lama


def get_paddle_ocr():
    """Singleton getter — inisialisasi PaddleOCR sekali, return instance yang sama."""
    global paddle_ocr_instance
    if paddle_ocr_instance is None:
        try:
            os.environ['FLAGS_enable_pir_api'] = '0'
            os.environ['FLAGS_use_mkldnn'] = '0'

            from paddleocr import PaddleOCR
            logger.info("Initializing PaddleOCR (optimized config)...")
            paddle_ocr_instance = PaddleOCR(
                use_angle_cls=True,   # DIPERTAHANKAN: foto bisa miring
                lang='en',
                show_log=False,       # matikan log verbose internal
                # ── Kurangi resolusi detection model ──────────────
                # Default PaddleOCR: 960px → kita turunkan ke 480px
                # Dampak: ~2-3x lebih cepat di detection step
                det_limit_side_len=480,
                det_limit_type='min',
                # ── Multi-threading CPU ────────────────────────────
                # Manfaatkan semua core VPS (biasanya 1-2 core di VPS 2GB)
                cpu_threads=2,
                # ── Recognition optimization ───────────────────────
                rec_batch_num=6,      # proses banyak baris teks sekaligus
            )
            logger.info("PaddleOCR initialized successfully (optimized).")
        except Exception as e:
            logger.error(f"Failed to initialize PaddleOCR: {e}")
            raise RuntimeError(f"PaddleOCR Initialization Error: {e}")
    return paddle_ocr_instance


def prewarm_ocr():
    """
    Pre-load PaddleOCR model ke RAM saat startup.
    Panggil ini dari FastAPI startup event agar request pertama tidak kena lag.
    """
    logger.info("Pre-warming PaddleOCR model...")
    try:
        ocr = get_paddle_ocr()
        # Jalankan dummy inference 1x1 pixel agar semua model ter-load ke memori
        dummy = np.ones((32, 200, 3), dtype=np.uint8) * 200
        ocr.ocr(dummy)
        logger.info("PaddleOCR pre-warm selesai — model siap digunakan.")
    except Exception as e:
        logger.warning(f"Pre-warm OCR gagal (tidak kritis): {e}")


class OCRProcessor:
    """
    Handles the extraction of text using PaddleOCR.
    Menggunakan image hash cache untuk menghindari re-inference gambar yang sama.
    """
    def __init__(self):
        self.ocr_model = get_paddle_ocr()

    def extract_text(self, image: np.ndarray) -> str:
        # ── Pastikan gambar dalam format BGR (3 channel) ──────
        # PaddleOCR LEBIH AKURAT dengan gambar berwarna (BGR)
        # daripada gambar grayscale/binary
        if len(image.shape) == 2:
            # Gambar grayscale → konversi ke BGR
            image = cv2.cvtColor(image, cv2.COLOR_GRAY2BGR)
        elif image.shape[2] == 4:
            # Gambar RGBA → hapus alpha channel
            image = cv2.cvtColor(image, cv2.COLOR_BGRA2BGR)

        # ── Cek cache dulu sebelum inference ─────────────────
        img_hash = _image_hash(image)
        cached = _cache_get(img_hash)
        if cached is not None:
            logger.info(f"OCR cache HIT (hash={img_hash[:8]}...) — skip inference")
            return cached

        logger.info("OCR cache MISS — menjalankan PaddleOCR inference...")
        try:
            result = self.ocr_model.ocr(image)
            extracted_lines = []

            def find_text_tuples(obj):
                if isinstance(obj, tuple) and len(obj) == 2 and isinstance(obj[0], str):
                    extracted_lines.append(obj[0])
                elif isinstance(obj, list):
                    for item in obj:
                        find_text_tuples(item)

            find_text_tuples(result)

            if not extracted_lines:
                logger.warning("OCR selesai tetapi tidak ada teks yang ditemukan.")
                text_result = ""
            else:
                text_result = "\n".join(extracted_lines)

            # Simpan ke cache
            _cache_put(img_hash, text_result)
            return text_result

        except Exception as e:
            logger.error(f"OCR processing failed: {str(e)}")
            raise RuntimeError(f"Failed to extract text using OCR: {str(e)}")


def extract_text_from_image(image: np.ndarray, **kwargs) -> str:
    """Extract text dari numpy array menggunakan PaddleOCR."""
    logger.info("extract_text_from_image dipanggil — menggunakan PaddleOCR.")
    ocr = OCRProcessor()
    return ocr.extract_text(image)


def extract_text_from_image_path(image_path: str, **kwargs) -> str:
    """Extract text dari file path menggunakan PaddleOCR."""
    logger.info(f"extract_text_from_image_path dipanggil untuk: {image_path}")
    from modules.preprocessing import preprocess_image
    processed_image = preprocess_image(image_path)
    ocr = OCRProcessor()
    return ocr.extract_text(processed_image)
