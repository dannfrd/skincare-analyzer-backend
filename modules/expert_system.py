import logging
from typing import List, Dict

logger = logging.getLogger(__name__)

class ExpertSystem:
    """
    A rule-based expert system that evaluates a list of skincare ingredients
    and generates safety scores, warnings, and recommendations based on 
    predefined domain rules.
    """
    
    def __init__(self):
        # Starting base score
        self.base_score = 100
        
    def _rule_comedogenic(self, ingredient: Dict) -> Optional[Dict]:
        """Rule 1: Check for high comedogenic rating."""
        rating = ingredient.get('comedogenic_rating', 0)
        # Usually, rating 4 or 5 is highly comedogenic (pore-clogging)
        if rating >= 4:
            return {
                "type": "comedogenic_warning",
                "ingredient": ingredient.get('name'),
                "rating": rating,
                "message": f"Highly comedogenic (rating {rating}). May clog pores for acne-prone skin.",
                "deduction": 10
            }
        elif rating == 3:
             return {
                "type": "comedogenic_caution",
                "ingredient": ingredient.get('name'),
                "rating": rating,
                "message": f"Moderately comedogenic (rating {rating}). Use with caution if acne-prone.",
                "deduction": 5
            }
        return None

    def _rule_allergens(self, ingredient: Dict) -> Optional[Dict]:
        """Rule 2: Check if marked as a common allergen or irritant."""
        is_allergen = ingredient.get('is_allergen', False)
        if is_allergen:
            return {
                "type": "allergen_warning",
                "ingredient": ingredient.get('name'),
                "message": "Known common allergen or strong irritant (e.g., strong fragrance/essential oil).",
                "deduction": 8
            }
        return None

    def _rule_pregnancy_safe(self, ingredient: Dict) -> Optional[Dict]:
        """Rule 3: Check if ingredient is flagged as unsafe for pregnancy."""
        not_safe = ingredient.get('unsafe_for_pregnancy', False)
        if not_safe:
            return {
                "type": "pregnancy_warning",
                "ingredient": ingredient.get('name'),
                "message": "Not recommended during pregnancy (e.g., certain Retinoids/Salicylic Acid).",
                "deduction": 0 # Handled as a rigid flag rather than a score deduction
            }
        return None

    def evaluate(self, matched_ingredients: List[Dict]) -> Dict:
        """
        Executes all rules on the matched ingredients to produce a final report.
        
        Args:
            matched_ingredients: Output from the ingredient_matching module.
            
        Returns:
            Dict: Final analysis report containing scores, flags, and breakdowns.
        """
        logger.info("Expert System is evaluating ingredients...")
        
        score = self.base_score
        flags = []
        unknown_ingredients = []
        
        for ing in matched_ingredients:
            if ing.get('status') == 'Unknown':
                unknown_ingredients.append(ing.get('name'))
                continue
                
            # Apply Rules
            comedogenic_flag = self._rule_comedogenic(ing)
            if comedogenic_flag:
                flags.append(comedogenic_flag)
                score -= comedogenic_flag["deduction"]
                
            allergen_flag = self._rule_allergens(ing)
            if allergen_flag:
                flags.append(allergen_flag)
                score -= allergen_flag["deduction"]
                
            pregnancy_flag = self._rule_pregnancy_safe(ing)
            if pregnancy_flag:
                flags.append(pregnancy_flag)
                
        # Ensure score doesn't drop below 0
        final_score = max(0, score)
        
        # Determine overall safety classification
        classification = "Safe"
        if final_score < 50:
            classification = "High Risk"
        elif final_score < 80:
            classification = "Moderate Risk"
            
        report = {
            "overall_score": final_score,
            "classification": classification,
            "total_ingredients_identified": len(matched_ingredients) - len(unknown_ingredients),
            "total_unknown": len(unknown_ingredients),
            "warnings_found": len(flags),
            "flags": flags,
            "unknown_list": unknown_ingredients
        }
        
        logger.info(f"Evaluation complete. Score: {final_score}/100")
        return report

# Helper function
def run_expert_system(matched_ingredients: List[Dict]) -> Dict:
    """Helper function to run the expert system rules."""
    system = ExpertSystem()
    return system.evaluate(matched_ingredients)
