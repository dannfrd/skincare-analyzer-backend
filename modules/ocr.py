"""
ocr.py - OCR Module (PaddleOCR)

Menggunakan PaddleOCR untuk ekstraksi teks.
Di-load sekali saat pertama dipanggil (lazy loading) dan menggunakan konfigurasi ringan (CPU only).
"""

import os
# Fix internal PaddlePaddle CPU bugs by disabling PIR and MKLDNN globally
os.environ['FLAGS_enable_pir_api'] = '0'
os.environ['FLAGS_use_mkldnn'] = '0'

import numpy as np
import logging
import cv2

logger = logging.getLogger(__name__)

paddle_ocr_instance = None

def get_paddle_ocr():
    global paddle_ocr_instance
    if paddle_ocr_instance is None:
        try:
            from paddleocr import PaddleOCR
            # Konfigurasi ringan sesuai requirement VPS 2GB RAM: CPU only, english model
            logger.info("Initializing PaddleOCR...")
            paddle_ocr_instance = PaddleOCR(use_angle_cls=True, lang='en')
            logger.info("PaddleOCR initialized successfully.")
        except Exception as e:
            logger.error(f"Failed to initialize PaddleOCR: {e}")
            raise RuntimeError(f"PaddleOCR Initialization Error: {e}")
    return paddle_ocr_instance


class OCRProcessor:
    """
    Handles the extraction of text using PaddleOCR.
    """
    def __init__(self):
        self.ocr_model = get_paddle_ocr()

    def extract_text(self, image: np.ndarray) -> str:
        logger.info(f"PaddleOCR extraction started")
        
        # Ensure image has 3 channels (PaddleOCR expects HxWx3)
        if len(image.shape) == 2:
            image = cv2.cvtColor(image, cv2.COLOR_GRAY2BGR)
            
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
                return ""
                
            return "\n".join(extracted_lines)
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
    # Gambar di-resize sebelum masuk ke OCR
    processed_image = preprocess_image(image_path)
    ocr = OCRProcessor()
    return ocr.extract_text(processed_image)
