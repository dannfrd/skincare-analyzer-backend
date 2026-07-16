import pytesseract
import numpy as np
import logging
import os

logger = logging.getLogger(__name__)

class OCRProcessor:
    """
    Handles the extraction of text from preprocessed images using Tesseract OCR.
    """
    
    def __init__(self, psm_mode: int = 6):
        """
        Args:
            psm_mode: Page Segmentation Mode. 
                      3 = Fully automatic page segmentation (default)
                      6 = Assume a single uniform block of text (good for lists)
        """
        # Configure tesseract parameters
        # --oem 3: Default LSTM OCR Engine
        # --psm N: Page segmentation mode
        self.config = f"--oem 3 --psm {psm_mode}"

        # Optional override for systems where tesseract is not on PATH.
        tesseract_cmd = os.getenv("TESSERACT_CMD", "").strip()
        if tesseract_cmd:
            pytesseract.pytesseract.tesseract_cmd = tesseract_cmd
        
        # IMPORTANT: Ensure Tesseract is installed on the system.
        # If tesseract is not in PATH (e.g., Windows), you must specify the path here:
        # pytesseract.pytesseract.tesseract_cmd = r'C:\Program Files\Tesseract-OCR\tesseract.exe'

    def extract_text(self, image: np.ndarray) -> str:
        """
        Extracts raw text from a given image array.
        
        Args:
            image: A preprocessed numpy array image.
            
        Returns:
            str: The raw text extracted from the image.
        """
        logger.info(f"Starting OCR text extraction with PSM mode {self.config}")
        
        try:
            # Run pytesseract OCR
            raw_text = pytesseract.image_to_string(image, config=self.config)
            
            if not raw_text.strip():
                logger.warning("OCR completed but no text was found in the image.")
            else:
                logger.debug("Successfully extracted text from image.")
                
            return raw_text
            
        except Exception as e:
            logger.error(f"OCR processing failed: {str(e)}")
            raise RuntimeError(f"Failed to extract text using OCR: {str(e)}")


# Import processors dari service modular PaddleOCR
try:
    from modules.paddleocr_service import PaddleOCRVLAPIProcessor, PaddleOCRLocalProcessor
except ImportError as e:
    logger.warning(f"Gagal mengimpor modul paddleocr_service: {e}")
    PaddleOCRVLAPIProcessor = None
    PaddleOCRLocalProcessor = None

# Backward compatibility alias
PaddleOCRProcessor = PaddleOCRLocalProcessor


def _is_weak_ocr(text: str) -> bool:
    """
    Menilai apakah teks hasil OCR terlalu lemah, terpotong, atau tidak memiliki substansi bahan (garbage text).
    Contoh: 'atoyo J P O' -> lemah/garbage.
    """
    cleaned = text.strip()
    if not cleaned or len(cleaned) < 35:
        return True
    words = [w for w in cleaned.split() if len(w) >= 2 and any(c.isalpha() for c in w)]
    if len(words) < 5:
        return True
    return False

def _pick_best_ocr_result(candidates: list) -> str:
    """
    Memilih teks hasil OCR terbaik dari beberapa kandidat engine berdasarkan skor validitas kata & karakter alfanumerik.
    """
    best_text = ""
    best_score = -1
    for text in candidates:
        if not text:
            continue
        cleaned = text.strip()
        words = [w for w in cleaned.split() if len(w) >= 2 and any(c.isalpha() for c in w)]
        alpha_count = sum(1 for c in cleaned if c.isalpha())
        score = len(words) * 10 + alpha_count
        if score > best_score:
            best_score = score
            best_text = text
    return best_text


def extract_text_from_image(image: np.ndarray, psm_mode: int = 6) -> str:
    """
    Helper function untuk menjalankan ekstraksi OCR pada numpy array.
    Menjamin kemurnian engine (MURNI PaddleOCR jika dipilih 'paddleocr' / 'paddleocr_vl',
    atau MURNI Tesseract jika dipilih 'tesseract').
    """
    engine = os.getenv("OCR_ENGINE", "tesseract").lower().strip()
    fallback_enabled = os.getenv("OCR_FALLBACK_ENABLED", "true").lower() == "true"
    candidates = []

    # 1. PURE PADDLEOCR-VL (Cloud AI Studio)
    if engine in ("paddleocr_vl", "paddleocr_api", "paddleocr_cloud"):
        if PaddleOCRVLAPIProcessor is not None:
            try:
                processor = PaddleOCRVLAPIProcessor()
                res_vl = processor.extract_text(image)
                if res_vl and not _is_weak_ocr(res_vl):
                    return res_vl
                if res_vl:
                    candidates.append(res_vl)
                    logger.warning(f"PaddleOCR-VL API menghasilkan teks lemah ({len(res_vl)} kar).")
            except Exception as e:
                logger.warning(f"PaddleOCR-VL API error ({e}).")
                if not fallback_enabled:
                    raise
        # Jika fallback aktif untuk paddleocr_vl, hanya fallback ke MURNI PaddleOCR Local (PP-OCRv4), BUKAN Tesseract!
        if PaddleOCRLocalProcessor is not None and fallback_enabled:
            try:
                logger.info("Mencoba fallback MURNI ke PaddleOCR Local (PP-OCRv4)...")
                processor_loc = PaddleOCRLocalProcessor()
                res_loc = processor_loc.extract_text(image)
                if res_loc:
                    candidates.append(res_loc)
            except Exception as e_loc:
                logger.debug(f"PaddleOCR Local fallback error: {e_loc}")
        if candidates:
            return _pick_best_ocr_result(candidates)
        raise RuntimeError("PaddleOCR-VL gagal menghasilkan teks valid.")

    # 2. PURE PADDLEOCR LOKAL (PP-OCRv4 MURNI DI PERANGKAT, TANPA CAMPUR TANGAN TESSERACT)
    if engine in ("paddleocr", "paddleocr_local"):
        if PaddleOCRLocalProcessor is not None:
            try:
                processor = PaddleOCRLocalProcessor()
                return processor.extract_text(image)
            except Exception as e:
                logger.error(f"PaddleOCR Local processing failed: {e}")
                raise RuntimeError(f"PaddleOCR Local (PP-OCRv4) gagal: {e}")
        else:
            raise RuntimeError("PaddleOCRLocalProcessor tidak tersedia atau belum terinstal.")

    # 3. PURE TESSERACT OCR
    if engine == "tesseract":
        ocr = OCRProcessor(psm_mode=psm_mode)
        return ocr.extract_text(image)

    # 4. HYBRID ENGINE (Kombinasi PaddleOCR + Tesseract)
    if PaddleOCRLocalProcessor is not None:
        try:
            candidates.append(PaddleOCRLocalProcessor().extract_text(image))
        except Exception:
            pass
    try:
        candidates.append(OCRProcessor(psm_mode=psm_mode).extract_text(image))
    except Exception:
        pass
    if candidates:
        return _pick_best_ocr_result(candidates)
    raise RuntimeError("Semua engine OCR tidak menghasilkan teks yang valid.")


def extract_text_from_image_path(image_path: str, psm_mode: int = 6) -> str:
    """
    Helper function untuk menjalankan ekstraksi OCR dari file path.
    Menjamin kemurnian engine (MURNI PaddleOCR jika dipilih 'paddleocr' / 'paddleocr_vl',
    atau MURNI Tesseract jika dipilih 'tesseract') sesuai kebutuhan riset TA.
    """
    engine = os.getenv("OCR_ENGINE", "tesseract").lower().strip()
    fallback_enabled = os.getenv("OCR_FALLBACK_ENABLED", "true").lower() == "true"
    candidates = []

    # 1. PURE PADDLEOCR-VL (Cloud AI Studio)
    if engine in ("paddleocr_vl", "paddleocr_api", "paddleocr_cloud"):
        if PaddleOCRVLAPIProcessor is not None:
            try:
                processor = PaddleOCRVLAPIProcessor()
                res_vl = processor.extract_text(image_path)
                if res_vl and not _is_weak_ocr(res_vl):
                    return res_vl
                if res_vl:
                    candidates.append(res_vl)
                    logger.warning(f"PaddleOCR-VL API menghasilkan teks lemah ({len(res_vl)} kar) pada {image_path}.")
            except Exception as e:
                logger.warning(f"PaddleOCR-VL API error ({e}) pada {image_path}.")
                if not fallback_enabled:
                    raise
        # Jika fallback aktif untuk paddleocr_vl, hanya fallback ke MURNI PaddleOCR Local (PP-OCRv4), BUKAN Tesseract!
        if PaddleOCRLocalProcessor is not None and fallback_enabled:
            try:
                logger.info("Mencoba fallback MURNI ke PaddleOCR Local (PP-OCRv4)...")
                processor_loc = PaddleOCRLocalProcessor()
                res_loc = processor_loc.extract_text(image_path)
                if res_loc:
                    candidates.append(res_loc)
            except Exception as e_loc:
                logger.debug(f"PaddleOCR Local fallback error: {e_loc}")
        if candidates:
            return _pick_best_ocr_result(candidates)
        raise RuntimeError(f"PaddleOCR-VL gagal menghasilkan teks valid untuk {image_path}.")

    # 2. PURE PADDLEOCR LOKAL (PP-OCRv4 MURNI DI PERANGKAT, TANPA CAMPUR TANGAN TESSERACT)
    if engine in ("paddleocr", "paddleocr_local"):
        if PaddleOCRLocalProcessor is not None:
            try:
                processor = PaddleOCRLocalProcessor()
                return processor.extract_text(image_path)
            except Exception as e:
                logger.error(f"PaddleOCR Local processing failed on {image_path}: {e}")
                raise RuntimeError(f"PaddleOCR Local (PP-OCRv4) gagal: {e}")
        else:
            raise RuntimeError("PaddleOCRLocalProcessor tidak tersedia atau belum terinstal.")

    # 3. PURE TESSERACT OCR
    if engine == "tesseract":
        from modules.preprocessing import preprocess_image
        processed_image = preprocess_image(image_path)
        ocr = OCRProcessor(psm_mode=psm_mode)
        return ocr.extract_text(processed_image)

    # 4. HYBRID ENGINE (Kombinasi PaddleOCR + Tesseract)
    if PaddleOCRLocalProcessor is not None:
        try:
            candidates.append(PaddleOCRLocalProcessor().extract_text(image_path))
        except Exception:
            pass
    try:
        from modules.preprocessing import preprocess_image
        candidates.append(OCRProcessor(psm_mode=psm_mode).extract_text(preprocess_image(image_path)))
    except Exception:
        pass
    if candidates:
        return _pick_best_ocr_result(candidates)
    raise RuntimeError("Semua engine OCR tidak menghasilkan teks yang valid.")
