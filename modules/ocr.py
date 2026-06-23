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
                    use_textline_orientation=False,
                    lang='en'
                )
            except Exception as e:
                logger.error(f"Failed to import/initialize PaddleOCR: {e}")
                raise RuntimeError(f"PaddleOCR initialization failed: {e}")
        return cls._ocr_instance

    def extract_text(self, image_path_or_array) -> str:
        ocr = self.get_instance()
        try:
            result = ocr.predict(image_path_or_array)
            lines = []
            if result:
                for res in result:
                    data = None
                    if hasattr(res, 'json'):
                        data = res.json
                    elif isinstance(res, dict):
                        data = res
                    
                    if isinstance(data, dict):
                        rec_texts = data.get("rec_texts")
                        if not rec_texts and "res" in data and isinstance(data["res"], dict):
                            rec_texts = data["res"].get("rec_texts")
                        if rec_texts:
                            lines.extend([str(t) for t in rec_texts])
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
        import cv2
        resized_temp_path = None
        target_path = image_path
        try:
            img = cv2.imread(image_path)
            if img is not None:
                height, width = img.shape[:2]
                max_side = max(height, width)
                if max_side > 800:
                    scale = 800.0 / max_side
                    new_width = int(width * scale)
                    new_height = int(height * scale)
                    resized_img = cv2.resize(img, (new_width, new_height), interpolation=cv2.INTER_AREA)
                    
                    base, ext = os.path.splitext(image_path)
                    resized_temp_path = f"{base}_resized{ext}"
                    cv2.imwrite(resized_temp_path, resized_img)
                    target_path = resized_temp_path
                    logger.info(f"Resized image from {width}x{height} to {new_width}x{new_height} for PaddleOCR speedup")
        except Exception as e:
            logger.warning(f"Failed to resize image for PaddleOCR: {e}")

        try:
            processor = PaddleOCRProcessor()
            return processor.extract_text(target_path)
        finally:
            if resized_temp_path and os.path.exists(resized_temp_path):
                try:
                    os.remove(resized_temp_path)
                except Exception:
                    pass
    else:
        # Standard Tesseract needs numpy array from preprocess_image
        from modules.preprocessing import preprocess_image
        processed_image = preprocess_image(image_path)
        ocr = OCRProcessor(psm_mode=psm_mode)
        return ocr.extract_text(processed_image)

