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

# Helper classes and functions for PaddleOCR integration
class PaddleOCRProcessor:
    _ocr_instance = None

    @classmethod
    def get_instance(cls):
        if cls._ocr_instance is None:
            logger.info("Initializing PaddleOCR instance...")
            # Setup environment variables to avoid PIR and connection issues
            os.environ["FLAGS_use_mkldnn"] = "0"
            os.environ["PADDLE_PDX_ENABLE_MKLDNN_BYDEFAULT"] = "0"
            os.environ["PADDLE_PDX_DISABLE_MODEL_SOURCE_CHECK"] = "True"
            
            try:
                from paddleocr import PaddleOCR
                cls._ocr_instance = PaddleOCR(
                    use_doc_orientation_classify=False,
                    use_doc_unwarping=False,
                    use_textline_orientation=True,
                    text_det_thresh=0.2,
                    text_det_box_thresh=0.5,
                    text_det_unclip_ratio=1.8,
                    lang='en',
                    ocr_version='PP-OCRv4',
                    cpu_threads=2,
                    enable_mkldnn=False
                )
            except Exception as e:
                logger.error(f"Failed to import/initialize PaddleOCR: {e}")
                raise RuntimeError(f"PaddleOCR initialization failed: {e}")
        return cls._ocr_instance

    def extract_text(self, image_path_or_array) -> str:
        ocr = self.get_instance()
        try:
            lines = []
            # Try PaddleOCR 3.x / PP-OCRv4 predict method first
            if hasattr(ocr, 'predict') and callable(getattr(ocr, 'predict')):
                try:
                    result = ocr.predict(image_path_or_array)
                    if result:
                        for res in result:
                            data = res.json if hasattr(res, 'json') else (res if isinstance(res, dict) else None)
                            if isinstance(data, dict):
                                rec_texts = data.get("rec_texts")
                                dt_polys = data.get("dt_polys")
                                if not rec_texts and "res" in data and isinstance(data["res"], dict):
                                    rec_texts = data["res"].get("rec_texts")
                                    dt_polys = data["res"].get("dt_polys")
                                
                                if rec_texts:
                                    if dt_polys and len(dt_polys) == len(rec_texts):
                                        try:
                                            paired = sorted(zip(dt_polys, rec_texts), key=lambda x: x[0][0][1] if x[0] and len(x[0]) > 0 else 0)
                                            lines.extend([str(t[1]) for t in paired])
                                        except Exception:
                                            lines.extend([str(t) for t in rec_texts])
                                    else:
                                        lines.extend([str(t) for t in rec_texts])
                    if lines:
                        return "\n".join(lines)
                except Exception as e_pred:
                    logger.debug(f"ocr.predict failed or not applicable: {e_pred}, falling back to ocr.ocr")

            # Fallback to standard ocr() method without cls=False
            result = ocr.ocr(image_path_or_array)
            if result:
                for res in result:
                    if res:
                        try:
                            res_sorted = sorted(res, key=lambda r: r[0][0][1] if r and len(r) > 0 and isinstance(r[0], (list, tuple)) else 0)
                        except Exception:
                            res_sorted = res
                        for line in res_sorted:
                            if line and len(line) > 1 and isinstance(line[1], (tuple, list)):
                                text = line[1][0]
                                if text:
                                    lines.append(str(text))
            return "\n".join(lines)
        except Exception as e:
            logger.error(f"PaddleOCR processing failed: {str(e)}")
            raise RuntimeError(f"Failed to extract text using PaddleOCR: {str(e)}")

# Helper functions
def extract_text_from_image(image: np.ndarray, psm_mode: int = 6) -> str:
    """Helper function to run the OCR extraction on a numpy array."""
    engine = os.getenv("OCR_ENGINE", "tesseract").lower().strip()
    if engine == "paddleocr":
        processor = PaddleOCRProcessor()
        return processor.extract_text(image)
    else:
        ocr = OCRProcessor(psm_mode=psm_mode)
        return ocr.extract_text(image)

def extract_text_from_image_path(image_path: str, psm_mode: int = 6) -> str:
    """Helper function to run the OCR extraction from a file path."""
    engine = os.getenv("OCR_ENGINE", "tesseract").lower().strip()
    if engine == "paddleocr":
        processor = PaddleOCRProcessor()
        return processor.extract_text(image_path)
    else:
        # Standard Tesseract needs numpy array from preprocess_image
        from modules.preprocessing import preprocess_image
        processed_image = preprocess_image(image_path)
        ocr = OCRProcessor(psm_mode=psm_mode)
        return ocr.extract_text(processed_image)

