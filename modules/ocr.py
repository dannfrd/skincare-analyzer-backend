import pytesseract
import numpy as np
import logging

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

# Helper function
def extract_text_from_image(image: np.ndarray, psm_mode: int = 6) -> str:
    """Helper function to run the OCR extraction."""
    ocr = OCRProcessor(psm_mode=psm_mode)
    return ocr.extract_text(image)
