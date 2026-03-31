"""Helper methods for FluxClient metadata extraction

Separated for clarity and testability.
"""
import json
import logging

logger = logging.getLogger(__name__)


def extract_seed_from_forge_response(response_data: dict) -> int:
    """Extract actual seed value from Forge API response
    
    Forge API returns generation metadata in the 'info' field as a JSON string.
    This function parses that field to extract the actual seed used.
    
    Args:
        response_data: Full API response dict
    
    Returns:
        int: Actual seed used (-1 if extraction fails)
    """
    try:
        # Forge API returns 'info' as a JSON string
        info_str = response_data.get("info", "")
        if not info_str:
            logger.warning("No 'info' field in Forge API response, using seed=-1")
            return -1
        
        # Parse info JSON
        info_data = json.loads(info_str)
        
        # Extract seed
        seed = info_data.get("seed", -1)
        
        if seed == -1:
            logger.warning("No 'seed' field in Forge API info, using seed=-1")
        else:
            logger.debug(f"Extracted actual seed from Forge API: {seed}")
        
        return seed
        
    except json.JSONDecodeError as e:
        logger.warning(f"Failed to parse Forge API 'info' field: {e}, using seed=-1")
        return -1
    except Exception as e:
        logger.warning(f"Unexpected error extracting seed: {e}, using seed=-1")
        return -1
