"""JSON sanitization utilities for LLM responses

Provides robust JSON cleaning functions to handle common LLM output issues:
- Markdown code blocks (```json ... ```)
- Extraneous text before/after JSON
- Invalid control characters
- Whitespace normalization
"""
import re
import logging


def sanitize_json_response(text: str, logger_name: str = "JSONSanitizer") -> str:
    """Sanitize LLM JSON response with 4-step cleaning process
    
    This function implements a comprehensive sanitization strategy to handle
    common JSON formatting issues in LLM responses:
    
    Step 1: Remove Markdown code blocks (```json ... ```)
    Step 2: Extract JSON object from surrounding text ({ ... })
    Step 3: Remove invalid control characters (except tabs/newlines)
    Step 4: Strip leading/trailing whitespace
    
    Args:
        text: Raw LLM response text
        logger_name: Logger name for debug output (e.g., "TopicCurator")
    
    Returns:
        str: Cleaned JSON string ready for parsing
    
    Example:
        >>> raw = '```json\\n{"key": "value"}\\n```'
        >>> sanitize_json_response(raw)
        '{"key": "value"}'
    """
    logger = logging.getLogger(logger_name)
    
    original_text = text
    text = text.strip()
    
    # Step 1: Remove Markdown code blocks
    if text.startswith("```"):
        lines = text.split("\n")
        # Remove first ```json or ``` line
        start = 1
        # Remove last ``` line
        end = len(lines) - 1 if lines and lines[-1].strip() == "```" else len(lines)
        text = "\n".join(lines[start:end])
        text = text.strip()
    
    # Step 2: Extract JSON object from surrounding text
    # Use proper brace matching to handle nested objects
    first_brace = text.find("{")
    if first_brace != -1:
        # Find matching closing brace with proper nesting
        depth = 0
        for i in range(first_brace, len(text)):
            if text[i] == '{':
                depth += 1
            elif text[i] == '}':
                depth -= 1
                if depth == 0:
                    # Found matching closing brace
                    text = text[first_brace:i + 1]
                    break
        else:
            # No matching closing brace found, use original rfind logic as fallback
            last_brace = text.rfind("}")
            if last_brace > first_brace:
                text = text[first_brace:last_brace + 1]
                logger.debug(f"[{logger_name}] Warning: Unbalanced braces, using fallback extraction")
    
    # Step 3: Remove invalid control characters (except tabs and newlines)
    # Preserve JSON-valid whitespace while removing problematic control chars
    text = re.sub(r'[\x00-\x08\x0b-\x0c\x0e-\x1f]', '', text)
    
    # Step 4: Strip leading/trailing whitespace
    text = text.strip()
    
    logger.debug(f"[{logger_name}] Sanitization: {len(original_text)} chars -> {len(text)} chars")
    
    return text


def sanitize_json_lightweight(text: str) -> str:
    """Lightweight JSON sanitization (code block removal only)
    
    For cases where full sanitization is not needed, this function
    only removes Markdown code fences (```json ... ```).
    
    Args:
        text: Raw LLM response text
    
    Returns:
        str: Cleaned JSON string with code blocks removed
    
    Example:
        >>> raw = '```json\\n{"key": "value"}\\n```'
        >>> sanitize_json_lightweight(raw)
        '{"key": "value"}'
    """
    sanitized = re.sub(r'^\s*```json\s*', '', text, flags=re.IGNORECASE)
    sanitized = re.sub(r'\s*```\s*$', '', sanitized)
    return sanitized.strip()
