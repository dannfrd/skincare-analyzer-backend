import difflib
import logging
import re
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
        Find the closest match in the database for a given token, applying chemical-aware
        guards (number differences and chemical prefix differences) to prevent false positives.
        """
        token_upper = token.upper().strip()
        
        # 1. Exact match check first
        if token_upper in self.known_names:
            return token_upper
            
        # 2. Get top 5 fuzzy candidates
        matches = difflib.get_close_matches(
            token_upper, 
            self.known_names, 
            n=5, 
            cutoff=threshold
        )
        
        chem_prefixes = ('DI', 'TRI', 'TETRA', 'POLY', 'MONO', 'HEXA', 'OCTA', 'METHYL', 'ETHYL', 'PROPYL', 'BUTYL', 'ISO')
        chem_roots = ('PARABEN', 'GLYCOL', 'GLYCERIN', 'SILOXANE', 'METHICONE', 'ALCOHOL', 'ACID', 'ETHER', 'ESTER', 'SULFATE', 'CHLORIDE')
        
        for match_name in matches:
            # Rule 1: Number Guard (e.g. Polysorbate 20 vs Polysorbate 60, PEG-40 vs PEG-60)
            nums_token = set(re.findall(r'\d+', token_upper))
            nums_match = set(re.findall(r'\d+', match_name))
            if nums_token and nums_match and nums_token != nums_match:
                continue
                
            # Rule 2: Chemical Prefix & Root Guard
            token_words = set(token_upper.split())
            match_words = set(match_name.split())
            
            prefix_conflict = False
            for tw in token_words:
                for mw in match_words:
                    if tw != mw and len(tw) > 3 and len(mw) > 3:
                        # Check if one is a prefix of another (e.g. PROPYLENE vs DIPROPYLENE)
                        for p in chem_prefixes:
                            if (tw.startswith(p) and tw[len(p):] == mw) or (mw.startswith(p) and mw[len(p):] == tw):
                                prefix_conflict = True
                                break
                        if prefix_conflict: break
                        
                        # Check chemical family root conflicts (e.g. METHYLPARABEN vs PROPYLPARABEN)
                        for root in chem_roots:
                            if tw.endswith(root) and mw.endswith(root) and tw != mw:
                                if difflib.SequenceMatcher(None, tw[:-len(root)], mw[:-len(root)]).ratio() < 0.7:
                                    prefix_conflict = True
                                    break
                        if prefix_conflict: break
                if prefix_conflict: break
                
            if not prefix_conflict:
                return match_name
                
        return None

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
