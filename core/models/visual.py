"""Visual identity data models for dynamic image generation"""
from typing import Optional
from pydantic import BaseModel, Field

# Default values for fallback scenarios (Issue #4)
DEFAULT_PRIMARY_COLOR = "electric cyan"
DEFAULT_SECONDARY_COLOR = "hot magenta"
DEFAULT_COLOR_MOOD = "cyberpunk futuristic"
DEFAULT_AESTHETIC = "Neon Cyberpunk"
# Tuple (immutable) to prevent accidental mutations
DEFAULT_VISUAL_KEYWORDS = ("neon", "futuristic", "cyberpunk")


class VisualIdentity(BaseModel):
    """Video-specific unified visual brand (Color Palette + Aesthetic Style)
    
    Represents the complete visual identity for a single video, ensuring
    consistency across all segment backgrounds and thumbnail while allowing
    dynamic aesthetic adaptation based on theme.
    """
    # Color Palette
    primary_color: str = Field(
        ...,
        description="Primary neon color with rich descriptors (e.g., 'electric cyan', 'vivid crimson')"
    )
    secondary_color: str = Field(
        ...,
        description="Secondary neon color with rich descriptors (e.g., 'hot magenta', 'golden amber')"
    )
    color_mood: str = Field(
        ...,
        description="Color-based mood/atmosphere (e.g., 'futuristic medical', 'warm nostalgic')"
    )
    
    # Aesthetic Style
    aesthetic: str = Field(
        ...,
        description="Primary aesthetic style (e.g., 'Clean Minimalist Modern', 'Cozy Lo-fi Studio', 'Dystopian Industrial')"
    )
    visual_keywords: list[str] = Field(
        default_factory=list,
        description="3-5 visual keywords defining the aesthetic (e.g., ['clinical', 'sterile', 'high-tech'])"
    )
    
    # Metadata
    reasoning: str = Field(
        default="",
        description="LLM reasoning for visual identity selection (for debugging/logging)"
    )
    
    def to_color_fragment(self) -> str:
        """Generate color palette fragment for FLUX.1 integration
        
        Returns:
            str: Formatted color palette description for prompt injection
        """
        return f"{self.primary_color} and {self.secondary_color} neon lighting"
    
    def to_aesthetic_fragment(self) -> str:
        """Generate aesthetic style fragment for FLUX.1 integration
        
        Returns:
            str: Formatted aesthetic description for prompt injection
        """
        if self.visual_keywords:
            keywords = ", ".join(self.visual_keywords[:3])
            return f"{self.aesthetic} aesthetic, {keywords}"
        return f"{self.aesthetic} aesthetic"
    
    def to_prompt_fragment(self) -> str:
        """Generate complete visual identity fragment for FLUX.1 integration
        
        Combines color palette and aesthetic for backward compatibility.
        
        Returns:
            str: Formatted visual identity description for prompt injection
        """
        # Issue #5 fix: Include aesthetic for true backward compatibility
        return f"{self.to_color_fragment()}, {self.to_aesthetic_fragment()}"
    
    def __str__(self) -> str:
        """Human-readable representation"""
        return f"{self.primary_color} × {self.secondary_color} ({self.color_mood}) | {self.aesthetic}"


# Issue #1 fix: Simple type alias instead of complex subclass
# This ensures isinstance() checks work correctly and avoids type confusion
VisualPalette = VisualIdentity


def create_visual_identity_from_legacy(
    primary_color: str,
    secondary_color: str,
    mood: str,
    reasoning: str = ""
) -> VisualIdentity:
    """Factory function for creating VisualIdentity from legacy VisualPalette parameters
    
    Args:
        primary_color: Primary neon color
        secondary_color: Secondary neon color
        mood: Color-based mood (legacy 'mood' field)
        reasoning: LLM reasoning
    
    Returns:
        VisualIdentity with default aesthetic values
    """
    return VisualIdentity(
        primary_color=primary_color,
        secondary_color=secondary_color,
        color_mood=mood,
        aesthetic=DEFAULT_AESTHETIC,
        visual_keywords=list(DEFAULT_VISUAL_KEYWORDS),  # Convert tuple to list
        reasoning=reasoning
    )
