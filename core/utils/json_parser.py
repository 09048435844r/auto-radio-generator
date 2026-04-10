"""Centralized JSON parsing utilities for LLM responses

Provides robust JSON parsing with sanitization, retry logic, and fallback handling.
This eliminates code duplication across TopicCurator, MetadataGenerator, and SegmentGenerator.
"""
import json
import logging
from typing import TypeVar, Callable, Optional

from rich.console import Console

from core.utils.json_sanitizer import sanitize_json_response

T = TypeVar('T')

logger = logging.getLogger(__name__)
console = Console()


def parse_llm_json_response(
    response_text: str,
    component_name: str,
    fallback_factory: Optional[Callable[[], dict]] = None
) -> dict:
    """Parse LLM JSON response with sanitization and fallback
    
    This function implements a robust 3-step parsing strategy:
    1. Try direct JSON parsing (strict=False for flexibility)
    2. If failed, sanitize and retry
    3. If still failed, use fallback factory (if provided) or raise
    
    Args:
        response_text: Raw LLM response text
        component_name: Component name for logging (e.g., "TopicCurator")
        fallback_factory: Optional factory function to generate fallback dict
    
    Returns:
        dict: Parsed JSON data
    
    Raises:
        json.JSONDecodeError: If parsing fails and no fallback provided
    
    Example:
        >>> def fallback():
        ...     return {"topics": [], "curator_reasoning": "Fallback"}
        >>> data = parse_llm_json_response(response, "TopicCurator", fallback)
    """
    # Step 1: Try direct parsing
    try:
        data = json.loads(response_text.strip(), strict=False)
        logger.debug(f"[{component_name}] JSON parsed successfully (direct)")
        return data
    except json.JSONDecodeError as e:
        # Log detailed error for debugging
        logger.error(f"[{component_name}] JSON parse error: {e}")
        logger.error(f"[{component_name}] Error position: line {e.lineno}, column {e.colno}, char {e.pos}")
        logger.error(f"[{component_name}] Full raw response ({len(response_text)} chars):\n{'='*80}\n{response_text}\n{'='*80}")
        
        # Step 2: Try sanitization
        console.print(f"[yellow]⚠️ [{component_name}] JSONパースエラー。サニタイズ処理を試行中...[/yellow]")
        cleaned = sanitize_json_response(response_text, component_name)
        logger.debug(f"[{component_name}] Sanitized text ({len(cleaned)} chars):\n{cleaned[:1000]}...")
        
        try:
            data = json.loads(cleaned, strict=False)
            console.print(f"[green]✓ [{component_name}] サニタイズ後のパースに成功[/green]")
            logger.info(f"[{component_name}] JSON parsed successfully (after sanitization)")
            return data
        except json.JSONDecodeError as e2:
            logger.error(f"[{component_name}] JSON parse failed after sanitization: {e2}")
            logger.error(f"[{component_name}] Sanitized text:\n{'='*80}\n{cleaned}\n{'='*80}")
            console.print(f"[red]✗ [{component_name}] サニタイズ後もJSONパースに失敗しました[/red]")
            
            # Step 3: Use fallback if provided
            if fallback_factory:
                console.print(f"[yellow]⚠️ [{component_name}] フォールバックデータを使用します[/yellow]")
                logger.warning(f"[{component_name}] Using fallback data")
                return fallback_factory()
            else:
                console.print(f"[red]✗ [{component_name}] フォールバックが定義されていません。エラーを投げます[/red]")
                raise  # Re-raise the sanitization error


def parse_and_validate_json(
    response_text: str,
    component_name: str,
    validator: Callable[[dict], T],
    fallback_factory: Optional[Callable[[], T]] = None
) -> T:
    """Parse JSON and validate with custom validator
    
    This is a higher-level function that combines parsing and validation.
    
    Args:
        response_text: Raw LLM response text
        component_name: Component name for logging
        validator: Function to validate and transform dict to desired type
        fallback_factory: Optional factory function to generate fallback object
    
    Returns:
        T: Validated object
    
    Raises:
        json.JSONDecodeError: If parsing fails and no fallback provided
        Exception: If validation fails
    
    Example:
        >>> def validate(data: dict) -> CurationResult:
        ...     return CurationResult(**data)
        >>> result = parse_and_validate_json(response, "TopicCurator", validate)
    """
    # Parse JSON
    try:
        data = parse_llm_json_response(
            response_text,
            component_name,
            fallback_factory=lambda: fallback_factory().model_dump() if fallback_factory else None
        )
    except json.JSONDecodeError:
        if fallback_factory:
            logger.warning(f"[{component_name}] JSON parsing failed, using fallback object")
            return fallback_factory()
        raise
    
    # Validate
    try:
        validated = validator(data)
        logger.debug(f"[{component_name}] Validation successful")
        return validated
    except Exception as e:
        logger.error(f"[{component_name}] Validation failed: {e}")
        if fallback_factory:
            logger.warning(f"[{component_name}] Using fallback object due to validation error")
            return fallback_factory()
        raise
