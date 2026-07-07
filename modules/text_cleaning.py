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
        """Fix common character misrecognitions and standard separators."""
        cleaned_text = text
        for wrong, right in self.ocr_mistakes.items():
            cleaned_text = cleaned_text.replace(wrong, right)
        # Convert bullet points and symbols acting as separators to commas
        cleaned_text = re.sub(r'[•·*|]', ',', cleaned_text)
        # Convert period followed by space or uppercase letter (e.g. METHICONE.METHYLMETHACRYLATE or SUCROSE LAURATE. DIPROPYLENE) to comma
        cleaned_text = re.sub(r'\.\s+(?=[A-Z])|\.(?=[A-Z]{3,})', ', ', cleaned_text)
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

        Strategy:
        1. Look for a known ingredient header keyword (Ingredients, Komposisi, etc.)
        2. Extract text from that point until a known stop-word (Cara Pakai, Warning, etc.)
        3. Fallback: score each line by ingredient-like heuristics and join the best ones.
        """
        if not raw_text:
            return ""

        normalized = raw_text.replace("\r", "\n")

        # --- Expanded header patterns ---
        marker_pattern = re.compile(
            r'(?:^|\n)[ \t]*'
            r'(INGREDIENTS?|KOMPOSISI(?:\s+BAHAN)?|COMPOSITION|'
            r'BAHAN(?:[-\s]BAHAN)?(?:\s+AKTIF)?|KANDUNGAN|INGR\.|INCI\s+NAME|'
            r'FORMULA(?:\s+BAHAN)?)'
            r'\s*[:\-/]?\s*',
            flags=re.IGNORECASE | re.MULTILINE,
        )

        # --- Expanded stop-word patterns (marks end of ingredient block) ---
        stop_pattern = re.compile(
            r'(?:^|\n|\s)'
            r'(HOW\s+TO\s+USE|DIRECTIONS?|USAGE|CARA\s+PAKAI|CARA\s+PENGGUNAAN|'
            r'ATURAN\s+PAKAI|PETUNJUK\s+PENGGUNAAN|PETUNJUK\s+PEMAKAIAN|'
            r'PERINGATAN|WARNING|CAUTION|PERHATIAN|KETERANGAN|'
            r'NETTO|NET\s*WT\.?|NET\s*CONTENT|BERAT\s+BERSIH|'
            r'BPOM|NO\.?\s*REG\.?|NOMOR\s+REGISTRASI|P[\-–]IRT|'
            r'EXP\.?|EXPIRED?|KADALUARSA|MFG\.?|MANUFACTURED|MADE\s+IN|'
            r'BATCH|LOT\s*NO\.?|DISIMPAN|SIMPAN\s+DI|STORAGE|'
            r'HALAL|CONTACT|DISTRIBUTOR|DIPRODUKSI\s+OLEH|DIPRODUKSI|'
            r'ALAMAT|ADDRESS|TEL\.|TELP\.?|PHONE|WEBSITE|HTTP|WWW\.|'
            r'KEGUNAAN|INDIKASI|KANDUNGAN\s+AKTIF(?=\s*:))'
            r'\s*[:\-]?',
            flags=re.IGNORECASE | re.MULTILINE,
        )

        marker_match = marker_pattern.search(normalized)
        if marker_match:
            ingredient_block = normalized[marker_match.end():]
            stop_match = stop_pattern.search(ingredient_block)
            if stop_match:
                ingredient_block = ingredient_block[:stop_match.start()]

            # Fix hyphenated line breaks (e.g. "Glycer-\nin" → "Glycerin")
            ingredient_block = re.sub(r'-\s*\n\s*', '', ingredient_block)
            # Collapse all remaining newlines to spaces (ingredient lists span lines)
            ingredient_block = re.sub(r'[\n\r]+', ' ', ingredient_block)
            # Collapse multiple spaces
            ingredient_block = re.sub(r'\s{2,}', ' ', ingredient_block)
            extracted = ingredient_block.strip()
            if len(extracted) >= 5:  # Sanity check: at least something meaningful
                return extracted

        # --- Fallback: score each line by ingredient-likelihood heuristics ---
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

    def clean_and_tokenize(
        self,
        raw_text: str,
        *,
        use_ai: bool = True,
    ) -> List[str]:
        """
        Main pipeline to clean the raw OCR string and split it into ingredients.
        Uses Gemini AI for extraction if available, falling back to regex.
        
        Args:
            raw_text: Raw string output from Tesseract.
            
        Returns:
            List[str]: A list of cleaned, individual ingredient names.
        """
        if not raw_text or not raw_text.strip():
            logger.warning("Empty string provided to TextCleaner")
            return []

        logger.info("Cleaning raw OCR text")

        if use_ai:
            try:
                from modules.gemini_ai import extract_ingredients_from_ocr
                ai_ingredients = extract_ingredients_from_ocr(raw_text)
                if ai_ingredients and len(ai_ingredients) > 0:
                    logger.info(
                        "Successfully extracted %s ingredients using AI.",
                        len(ai_ingredients),
                    )
                    cleaned_ingredients = []
                    seen = set()
                    for ingredient in ai_ingredients:
                        normalized = re.sub(r'\s+', ' ', ingredient).strip(' .-')
                        if len(normalized) <= 1 or normalized.isnumeric():
                            continue
                        if normalized in seen:
                            continue
                        seen.add(normalized)
                        cleaned_ingredients.append(normalized)
                    if cleaned_ingredients:
                        return cleaned_ingredients
                else:
                    logger.warning(
                        "AI extraction returned empty. Falling back to regex."
                    )
            except Exception as e:
                logger.error(
                    "Failed to use AI for ingredient extraction: %s. "
                    "Falling back to regex.",
                    e,
                )

        # FALLBACK: Regex based extraction
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
        
        # 6. Split by comma (standard INCI format)
        raw_ingredients = [item.strip() for item in re.split(r'[,;]', text)]
        
        # 7. Filter and de-duplicate while preserving order
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
        
        logger.debug(f"Successfully tokenized {len(cleaned_ingredients)} ingredients via fallback.")
        return cleaned_ingredients

# Helper function
def clean_text_pipeline(raw_text: str, *, use_ai: bool = True) -> List[str]:
    """Helper function to rapidly clean and split raw text."""
    cleaner = TextCleaner()
    return cleaner.clean_and_tokenize(raw_text, use_ai=use_ai)


def extract_ingredient_text(raw_text: str) -> str:
    """Helper function to isolate ingredient text from OCR or free-form input."""
    cleaner = TextCleaner()
    return cleaner.extract_ingredient_text(raw_text)
