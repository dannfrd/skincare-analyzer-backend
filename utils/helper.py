import logging
import json
from typing import Dict, Any

def setup_logger(name: str = "skincare_analyzer") -> logging.Logger:
    """
    Configures and returns a standard logger for the application.
    """
    logger = logging.getLogger(name)
    
    # Check if handlers already exist to avoid duplicate logs
    if not logger.handlers:
        logger.setLevel(logging.DEBUG)
        
        # Console handler
        ch = logging.StreamHandler()
        ch.setLevel(logging.INFO) # Set to INFO by default for cleaner CLI output
        
        # Formatter
        formatter = logging.Formatter('%(asctime)s - %(name)s - %(levelname)s - %(message)s')
        ch.setFormatter(formatter)
        
        logger.addHandler(ch)
        
    return logger

def format_response(status: str, message: str, data: Any = None) -> Dict[str, Any]:
    """
    Standardizes the API response format.
    
    Args:
        status: "success" or "error"
        message: Human readable message
        data: Payload (dict, list, etc.)
        
    Returns:
        Dict representing the standardized JSON response.
    """
    response = {
        "status": status,
        "message": message
    }
    if data is not None:
        response["data"] = data
        
    return response

def print_json(data: Dict):
    """Utility to pretty-print JSON (useful for CLI/Debugging)."""
    print(json.dumps(data, indent=4))
