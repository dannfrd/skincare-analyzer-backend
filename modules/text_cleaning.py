import re
import logging
from typing import List

logger = logging.getLogger(__name__)

class TextCleaner:
    """
    Responsible for taking raw OCR output and cleaning it into a structured
    list of individual ingredient tokens.
    """
    
    def __init__(self):
        # Common OCR mistakes mapping (Tesseract sometimes confuses these)
        self.ocr_mistakes = {
            'l': 'I',
            '|': 'I',
            '1': 'I',
            '0': 'O',
            '\n': ' ', # Replace physical line breaks with spaces
            '[': ' ',
            ']': ' ',
            '{': ' ',
            '}': ' ',
            '—': '-',
        }

    def _fix_ocr_typos(self, text: str) -> str:
        """Fix common character misrecognitions."""
        cleaned_text = text
        for wrong, right in self.ocr_mistakes.items():
            cleaned_text = cleaned_text.replace(wrong, right)
        return cleaned_text

    def _remove_junk_characters(self, text: str) -> str:
        """Removes non-alphanumeric characters except basic punctuation needed."""
        # Keep letters, numbers, spaces, commas, hyphens, parentheses, and periods
        cleaned = re.sub(r'[^a-zA-Z0-9\s,\-\.\(\)]', '', text)
        return cleaned

    def clean_and_tokenize(self, raw_text: str) -> List[str]:
        """
        Main pipeline to clean the raw OCR string and split it into ingredients.
        
        Args:
            raw_text: Raw string output from Tesseract.
            
        Returns:
            List[str]: A list of cleaned, individual ingredient names.
        """
        if not raw_text or not raw_text.strip():
            logger.warning("Empty string provided to TextCleaner")
            return []

        logger.info("Cleaning raw OCR text")
        
        # 1. Strip whitespace
        text = raw_text.strip()
        
        # 2. Convert to uppercase for standardization (INCI names are often uppercase)
        text = text.upper()
        
        # 3. Fix simple OCR mistakes (line breaks to spaces, etc.)
        text = self._fix_ocr_typos(text)
        
        # 4. Remove unnecessary symbols
        text = self._remove_junk_characters(text)
        
        # 5. Remove 'INGREDIENTS:' preamble if it exists
        # E.g., "INGREDIENTS: Water, Glycerin..."
        text = re.sub(r'(?i)INGREDIENTS?\s*[:\-]?\s*', '', text)
        
        # 6. Some labels use '.' instead of ',' to separate ingredients by mistake
        # This is a heuristic, adjust if it breaks valid names (like 'CI 77891.')
        # For now, we mainly split by comma.
        
        # 7. Split by comma (standard INCI format)
        raw_ingredients = [item.strip() for item in text.split(',')]
        
        # 8. Filter out empty strings or single characters
        cleaned_ingredients = [
            ing for ing in raw_ingredients 
            if len(ing) > 1 and not ing.isnumeric()
        ]
        
        logger.debug(f"Successfully tokenized {len(cleaned_ingredients)} ingredients.")
        return cleaned_ingredients

# Helper function
def clean_text_pipeline(raw_text: str) -> List[str]:
    """Helper function to rapidly clean and split raw text."""
    cleaner = TextCleaner()
    return cleaner.clean_and_tokenize(raw_text)
