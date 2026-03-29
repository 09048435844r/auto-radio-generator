"""Visual identity data models for dynamic image generation"""
from pydantic import BaseModel, Field


class VisualPalette(BaseModel):
    """Video-specific visual identity with dynamic color palette
    
    Represents the unified visual brand for a single video, ensuring
    consistency across all segment backgrounds and thumbnail.
    """
    primary_color: str = Field(
        ...,
        description="Primary neon color with rich descriptors (e.g., 'electric cyan', 'vivid crimson')"
    )
    secondary_color: str = Field(
        ...,
        description="Secondary neon color with rich descriptors (e.g., 'hot magenta', 'golden amber')"
    )
    mood: str = Field(
        ...,
        description="Overall visual mood/atmosphere (e.g., 'futuristic medical', 'dystopian urban')"
    )
    reasoning: str = Field(
        default="",
        description="LLM reasoning for color selection (for debugging/logging)"
    )
    
    def to_prompt_fragment(self) -> str:
        """Generate prompt fragment for FLUX.1 integration
        
        Returns:
            str: Formatted color palette description for prompt injection
        """
        return f"{self.primary_color} and {self.secondary_color} neon lighting"
    
    def __str__(self) -> str:
        """Human-readable representation"""
        return f"{self.primary_color} × {self.secondary_color} ({self.mood})"
