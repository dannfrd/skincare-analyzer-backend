"""
ocr.py - OCR Module (Legacy / Minimal)

Catatan: Sejak integrasi Google MLKit di Flutter, proses OCR dilakukan
sepenuhnya on-device di HP pengguna. Backend tidak lagi memproses gambar.

Modul ini dipertahankan untuk kompatibilitas mundur endpoint /analyze-image
yang mungkin masih diuji secara manual via Postman/curl.
"""

pytesseract = None
try:
    import pytesseract
except ImportError:
    pass

import numpy as np
import logging
import os

logger = logging.getLogger(__name__)


class OCRProcessor:
    """
    Handles the extraction of text from preprocessed images using Tesseract OCR.
    Digunakan sebagai fallback minimal jika endpoint /analyze-image masih dipanggil.
    """

    def __init__(self, psm_mode: int = 6):
        if pytesseract is None:
            raise RuntimeError(
                "Library 'pytesseract' tidak terpasang. "
                "Install dengan 'pip install pytesseract' jika diperlukan."
            )
        self.config = f"--oem 3 --psm {psm_mode}"
        tesseract_cmd = os.getenv("TESSERACT_CMD", "").strip()
        if tesseract_cmd:
            pytesseract.pytesseract.tesseract_cmd = tesseract_cmd

    def extract_text(self, image: np.ndarray) -> str:
        logger.info(f"Tesseract OCR extraction (PSM: {self.config})")
        try:
            raw_text = pytesseract.image_to_string(image, config=self.config)
            if not raw_text.strip():
                logger.warning("OCR selesai tetapi tidak ada teks yang ditemukan.")
            return raw_text
        except Exception as e:
            logger.error(f"OCR processing failed: {str(e)}")
            raise RuntimeError(f"Failed to extract text using OCR: {str(e)}")


def extract_text_from_image(image: np.ndarray, psm_mode: int = 6) -> str:
    """Extract text dari numpy array menggunakan Tesseract (fallback minimal)."""
    logger.info("extract_text_from_image dipanggil — gunakan Tesseract sebagai fallback.")
    ocr = OCRProcessor(psm_mode=psm_mode)
    return ocr.extract_text(image)


def extract_text_from_image_path(image_path: str, psm_mode: int = 6) -> str:
    """Extract text dari file path menggunakan Tesseract (fallback minimal)."""
    logger.info(f"extract_text_from_image_path dipanggil untuk: {image_path}")
    from modules.preprocessing import preprocess_image
    processed_image = preprocess_image(image_path)
    ocr = OCRProcessor(psm_mode=psm_mode)
    return ocr.extract_text(processed_image)
