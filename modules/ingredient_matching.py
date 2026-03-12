import difflib
import logging
from typing import List, Dict, Optional

logger = logging.getLogger(__name__)

class IngredientMatcher:
    """
    Matches raw/cleaned OCR tokens against a database of known ingredients.
    Uses fuzzy string matching to handle minor OCR errors or spelling variations.
    """
    
    def __init__(self, database_ingredients: List[Dict]):
        """
        Args:
            database_ingredients: List of dictionary objects representing the DB rows.
                                  Expected format: [{"id": 1, "name": "WATER", ...}, ...]
        """
        self.db = database_ingredients
        # Extract just the names (uppercase) for fast matching
        self.known_names = [ing['name'].upper() for ing in self.db if 'name' in ing]
        
    def _find_best_match(self, token: str, threshold: float = 0.8) -> Optional[str]:
        """
        Find the closest match in the database for a given token.
        
        Args:
            token: The raw ingredient string from OCR.
            threshold: Minimum acceptable similarity (0.0 to 1.0).
            
        Returns:
            The matched string from the database if found, else None.
        """
        # difflib.get_close_matches returns a list of matches ordered by similarity
        matches = difflib.get_close_matches(
            token.upper(), 
            self.known_names, 
            n=1, 
            cutoff=threshold
        )
        
        return matches[0] if matches else None

    def _get_ingredient_data(self, name: str) -> Optional[Dict]:
        """Retrieve full ingredient data dictionary by exact name match."""
        for ing in self.db:
            if ing.get('name', '').upper() == name:
                return ing
        return None

    def match_ingredients(self, tokens: List[str]) -> List[Dict]:
        """
        Takes a list of cleaned OCR tokens and maps them to database entries.
        
        Args:
            tokens: List of extracted ingredient names.
            
        Returns:
            List[Dict]: List of matched ingredient data objects. Unmatched items 
                        are returned as "Unknown" placeholder objects.
        """
        logger.info(f"Matching {len(tokens)} tokens against database...")
        
        matched_results = []
        for token in tokens:
            best_match_name = self._find_best_match(token)
            
            if best_match_name:
                # Retrieve the full data for the matched ingredient
                data = self._get_ingredient_data(best_match_name)
                if data:
                    # Provide the original OCR text for debugging/transparency
                    result = dict(data) # copy to avoid modifying original db reference
                    result['ocr_token_used'] = token
                    matched_results.append(result)
            else:
                logger.debug(f"No sufficient match found for token: '{token}'")
                matched_results.append({
                    "name": token.upper(),
                    "status": "Unknown",
                    "comedogenic_rating": 0,
                    "is_allergen": False,
                    "description": "Ingredient not found in database.",
                    "ocr_token_used": token
                })
                
        logger.info(f"Successfully matched {len([m for m in matched_results if m.get('status') != 'Unknown'])} out of {len(tokens)} ingredients.")
        return matched_results

# Helper function
def match_tokens_to_db(tokens: List[str], db_data: List[Dict]) -> List[Dict]:
    """Helper function to run the matching pipeline."""
    matcher = IngredientMatcher(database_ingredients=db_data)
    return matcher.match_ingredients(tokens)
