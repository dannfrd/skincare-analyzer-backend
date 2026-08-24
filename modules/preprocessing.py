import cv2
import numpy as np
import logging

# Configure logger for this module
logger = logging.getLogger(__name__)


class ImagePreprocessor:
    """
    Handles image preprocessing steps to improve OCR accuracy.

    Strategi optimasi untuk VPS 2GB RAM:
    - target_width 640px (turun dari 1024px) → ~2.5x lebih cepat di PaddleOCR inference
    - Gambar BGR berwarna langsung ke PaddleOCR (LEBIH AKURAT daripada binary/grayscale)
    - Hapus adaptive thresholding: PaddleOCR modern TIDAK memerlukan binary image,
      justru lebih akurat dengan warna karena model terlatih dengan data berwarna.
    """

    def __init__(self, target_width: int = 640):
        # Turunkan dari 1024 → 640: area berkurang ~2.5x, inference lebih cepat secara kuadratik
        self.target_width = target_width

    def _resize_image(self, image: np.ndarray) -> np.ndarray:
        """
        Resizes the image to a standard width while maintaining aspect ratio.
        Hanya resize jika gambar lebih besar dari target — tidak pernah upscale.
        """
        height, width = image.shape[:2]
        if width > self.target_width:
            scaling_factor = self.target_width / float(width)
            new_size = (self.target_width, int(height * scaling_factor))
            resized = cv2.resize(image, new_size, interpolation=cv2.INTER_AREA)
            logger.debug(f"Resized image from {width}x{height} to {new_size}")
            return resized
        return image

    def process(self, image_path: str) -> np.ndarray:
        """
        Main preprocessing pipeline: Load → Resize → Return BGR.

        CATATAN: Adaptive thresholding (grayscale + binary) DIHAPUS karena:
        1. PaddleOCR dirancang untuk gambar BGR berwarna, bukan binary
        2. Konversi ke grayscale justru membuang informasi warna yang dipakai model
        3. Gambar kemasan skincare seringkali berwarna-warni — binary memperburuk deteksi
        4. Menghapus 2 langkah = lebih cepat preprocessing

        Args:
            image_path: Path to the input image file.

        Returns:
            np.ndarray: Gambar BGR yang sudah di-resize, siap untuk PaddleOCR.

        Raises:
            FileNotFoundError: If the image cannot be loaded.
        """
        logger.info(f"Starting preprocessing for {image_path}")

        # 1. Load Image
        image = cv2.imread(image_path)
        if image is None:
            logger.error(f"Failed to load image at {image_path}")
            raise FileNotFoundError(f"Image not found or unreadable: {image_path}")

        # 2. Resize (satu-satunya langkah preprocessing yang diperlukan)
        processed_img = self._resize_image(image)

        logger.info(f"Image preprocessing completed — output: {processed_img.shape[1]}x{processed_img.shape[0]} BGR")
        return processed_img


def preprocess_image(image_path: str) -> np.ndarray:
    """Helper function to run the full preprocessing pipeline."""
    preprocessor = ImagePreprocessor()
    return preprocessor.process(image_path)
