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

    def extract_ingredient_text(self, raw_text: str) -> str:
        """
        Extract the ingredient section only, so downstream matching and AI prompting
        avoid unrelated packaging text.
        """
        if not raw_text:
            return ""

        normalized = raw_text.replace("\r", "\n")
        marker_pattern = re.compile(
            r'(INGREDIENTS?|KOMPOSISI|COMPOSITION)\s*[:\-]?\s*',
            flags=re.IGNORECASE,
        )
        stop_pattern = re.compile(
            r'\b(HOW TO USE|DIRECTIONS?|USAGE|CARA PAKAI|PERINGATAN|WARNING|CAUTION|NETTO|NET WT|BPOM|EXP\.?|MFG\.?|MANUFACTURED|MADE IN|BATCH|LOT)\b',
            flags=re.IGNORECASE,
        )

        marker_match = marker_pattern.search(normalized)
        if marker_match:
            ingredient_block = normalized[marker_match.end():]
            stop_match = stop_pattern.search(ingredient_block)
            if stop_match:
                ingredient_block = ingredient_block[:stop_match.start()]
            extracted = ingredient_block.strip()
            if extracted:
                return extracted

        lines = [line.strip() for line in normalized.splitlines() if line.strip()]
        if not lines:
            return normalized.strip()

        def line_score(line: str) -> int:
            upper_line = line.upper()
            if stop_pattern.search(upper_line):
                return -5

            alpha_chars = [ch for ch in line if ch.isalpha()]
            uppercase_ratio = (
                sum(1 for ch in alpha_chars if ch.isupper()) / len(alpha_chars)
                if alpha_chars else 0
            )

            return (
                (line.count(",") * 3)
                + (2 if ";" in line else 0)
                + (2 if uppercase_ratio >= 0.6 else 0)
                + (1 if len(line) >= 25 else 0)
            )

        candidate_lines = [line for line in lines if line_score(line) >= 3]
        if candidate_lines:
            return ", ".join(candidate_lines)

        return normalized.strip()

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

        ingredient_text = self.extract_ingredient_text(raw_text)
        if not ingredient_text:
            return []
        
        # 1. Strip whitespace
        text = ingredient_text.strip()
        
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
        raw_ingredients = [item.strip() for item in re.split(r'[,;]', text)]
        
        # 8. Filter and de-duplicate while preserving order
        cleaned_ingredients = []
        seen = set()
        for ingredient in raw_ingredients:
            normalized_ingredient = re.sub(r'\s+', ' ', ingredient).strip(' .-')
            if len(normalized_ingredient) <= 1 or normalized_ingredient.isnumeric():
                continue
            if normalized_ingredient in seen:
                continue
            seen.add(normalized_ingredient)
            cleaned_ingredients.append(normalized_ingredient)
        
        logger.debug(f"Successfully tokenized {len(cleaned_ingredients)} ingredients.")
        return cleaned_ingredients

# Helper function
def clean_text_pipeline(raw_text: str) -> List[str]:
    """Helper function to rapidly clean and split raw text."""
    cleaner = TextCleaner()
    return cleaner.clean_and_tokenize(raw_text)


def extract_ingredient_text(raw_text: str) -> str:
    """Helper function to isolate ingredient text from OCR or free-form input."""
    cleaner = TextCleaner()
    return cleaner.extract_ingredient_text(raw_text)
