"""Response Validator - Defensive validation for LLM outputs"""
import json
import re
from typing import Any, TypeVar, Type
from pydantic import BaseModel, ValidationError

from core.utils import sanitize_json_response
from core.interfaces.llm_port import LLMResponseError


T = TypeVar('T', bound=BaseModel)


class ResponseValidator:
    """Validates and sanitizes LLM responses
    
    Responsibilities:
    1. Extract JSON from various formats (code blocks, plain text)
    2. Sanitize malformed JSON (trailing commas, unescaped quotes)
    3. Validate against Pydantic schema
    4. Provide detailed error messages for debugging
    """
    
    @staticmethod
    def validate_json_response(
        raw_response: str,
        schema: Type[T],
        provider: str
    ) -> T:
        """Validate and parse JSON response
        
        Args:
            raw_response: Raw LLM response text
            schema: Pydantic model class for validation
            provider: Provider name (for error messages)
            
        Returns:
            Validated Pydantic model instance
            
        Raises:
            LLMResponseError: If validation fails
        """
        # Step 1: Extract JSON from code blocks
        json_text = ResponseValidator._extract_json(raw_response)
        
        # Step 2: Sanitize JSON
        json_text = sanitize_json_response(json_text)
        
        # Step 3: Parse JSON
        try:
            data = json.loads(json_text)
        except json.JSONDecodeError as e:
            raise LLMResponseError(
                f"[{provider}] Invalid JSON response: {e}\n"
                f"Raw response (first 500 chars): {raw_response[:500]}"
            ) from e
        
        # Step 4: Validate against schema
        try:
            return schema.model_validate(data)
        except ValidationError as e:
            raise LLMResponseError(
                f"[{provider}] Schema validation failed: {e}\n"
                f"Data: {json.dumps(data, indent=2, ensure_ascii=False)[:500]}"
            ) from e
    
    @staticmethod
    def _extract_json(text: str) -> str:
        """Extract JSON from various formats"""
        # Remove markdown code blocks
        text = re.sub(r'```json\s*', '', text)
        text = re.sub(r'```\s*', '', text)
        
        # Find JSON object/array
        json_match = re.search(r'(\{.*\}|\[.*\])', text, re.DOTALL)
        if json_match:
            return json_match.group(1)
        
        return text.strip()
    
    @staticmethod
    def validate_required_fields(
        data: dict,
        required_fields: list[str],
        provider: str
    ) -> None:
        """Validate required fields exist
        
        Raises:
            LLMResponseError: If required field is missing
        """
        missing = [f for f in required_fields if f not in data]
        if missing:
            raise LLMResponseError(
                f"[{provider}] Missing required fields: {', '.join(missing)}\n"
                f"Available fields: {', '.join(data.keys())}"
            )
    
    @staticmethod
    def truncate_list(
        items: list[Any],
        max_length: int,
        item_name: str,
        provider: str
    ) -> list[Any]:
        """Truncate list to max length with warning
        
        Args:
            items: List to truncate
            max_length: Maximum allowed length
            item_name: Name of items (for logging)
            provider: Provider name (for logging)
            
        Returns:
            Truncated list
        """
        if len(items) > max_length:
            from rich.console import Console
            console = Console()
            console.print(
                f"[yellow]⚠️ [{provider}] Generated {len(items)} {item_name}, "
                f"truncating to {max_length}[/yellow]"
            )
            return items[:max_length]
        return items
