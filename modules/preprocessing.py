import cv2
import numpy as np
import logging

# Configure logger for this module
logger = logging.getLogger(__name__)

class ImagePreprocessor:
    """
    Handles image preprocessing steps to improve OCR accuracy.
    Includes resizing, grayscale conversion, denoising, and thresholding.
    """
    
    def __init__(self, target_width: int = 1024):
        self.target_width = target_width

    def _resize_image(self, image: np.ndarray) -> np.ndarray:
        """
        Resizes the image to a standard width while maintaining aspect ratio.
        """
        height, width = image.shape[:2]
        if width > self.target_width:
            scaling_factor = self.target_width / float(width)
            new_size = (self.target_width, int(height * scaling_factor))
            resized = cv2.resize(image, new_size, interpolation=cv2.INTER_AREA)
            logger.debug(f"Resized image from {width}x{height} to {new_size}")
            return resized
        return image

    def _apply_thresholding(self, gray_image: np.ndarray) -> np.ndarray:
        """
        Applies adaptive thresholding to create a binary image (black & white).
        Useful for dealing with uneven lighting on cylindrical bottles.
        """
        # Apply Gaussian Blur to reduce noise before thresholding
        blurred = cv2.GaussianBlur(gray_image, (5, 5), 0)
        
        # Adaptive thresholding: calculates threshold for small regions
        binary = cv2.adaptiveThreshold(
            blurred, 
            255, 
            cv2.ADAPTIVE_THRESH_GAUSSIAN_C, 
            cv2.THRESH_BINARY, 
            11, 
            2
        )
        return binary

    def process(self, image_path: str) -> np.ndarray:
        """
        Main preprocessing pipeline: Load -> Resize -> Grayscale -> Threshold.
        
        Args:
            image_path: Path to the input image file.
            
        Returns:
            np.ndarray: The preprocessed binary image ready for OCR.
            
        Raises:
            FileNotFoundError: If the image cannot be loaded.
        """
        logger.info(f"Starting preprocessing for {image_path}")
        
        # 1. Load Image
        image = cv2.imread(image_path)
        if image is None:
            logger.error(f"Failed to load image at {image_path}")
            raise FileNotFoundError(f"Image not found or unreadable: {image_path}")
            
        # 2. Resize
        resized_image = self._resize_image(image)
        
        # 3. Convert to Grayscale
        gray = cv2.cvtColor(resized_image, cv2.COLOR_BGR2GRAY)
        
        # 4. Thresholding (Binarization)
        processed_img = self._apply_thresholding(gray)
        
        logger.info("Image preprocessing completed successfully")
        return processed_img

# Example usage function
def preprocess_image(image_path: str) -> np.ndarray:
    """Helper function to run the full preprocessing pipeline."""
    preprocessor = ImagePreprocessor()
    return preprocessor.process(image_path)
