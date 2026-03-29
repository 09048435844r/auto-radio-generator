"""Visual palette generator for dynamic color-driven image generation"""
import logging
from typing import Optional

from google import genai
from google.genai import types
from rich.console import Console

from core.models import AppConfig
from core.models.visual import VisualPalette

logger = logging.getLogger(__name__)
console = Console()


class VisualPaletteGenerator:
    """LLM-based visual palette generator
    
    Uses Gemini Flash to generate a unique color palette for each video,
    ensuring visual brand consistency across all segments and thumbnail.
    """
    
    SYSTEM_PROMPT = """You are a professional color theorist and cinematographer specializing in cyberpunk/vaporwave aesthetics.

Your task is to generate a UNIQUE, THEMATIC color palette for a video based on its theme and content.

REQUIREMENTS:
1. Select TWO neon colors that:
   - Are VISUALLY DISTINCTIVE and create strong contrast
   - Reflect the video's theme and mood
   - Work well in cyberpunk/vaporwave aesthetic
   - Use RICH, EVOCATIVE descriptors (e.g., "electric cyan" NOT "blue")

2. Color naming guidelines:
   - ✅ GOOD: "electric cyan", "hot magenta", "vivid crimson", "golden amber", "toxic green", "deep violet"
   - ❌ BAD: "blue", "red", "green", "purple" (too generic)
   - ✅ GOOD: "neon pink", "acid yellow", "plasma blue", "laser red"
   - ❌ BAD: "light blue", "dark red" (not evocative enough)

3. Mood description:
   - Capture the overall visual atmosphere in 2-4 words
   - Examples: "futuristic medical", "dystopian urban", "retro-tech nostalgia"

OUTPUT FORMAT (JSON):
{
  "primary_color": "<rich color descriptor>",
  "secondary_color": "<rich color descriptor>",
  "mood": "<2-4 word atmosphere>",
  "reasoning": "<brief explanation of color choice>"
}

EXAMPLES:

Theme: "持続血糖測定器CGMについて"
{
  "primary_color": "electric cyan",
  "secondary_color": "hot magenta",
  "mood": "futuristic medical",
  "reasoning": "Cyan evokes medical technology and data displays, magenta adds human vitality and urgency"
}

Theme: "都市伝説の真相"
{
  "primary_color": "toxic green",
  "secondary_color": "deep violet",
  "mood": "mysterious paranormal",
  "reasoning": "Green suggests the uncanny and supernatural, violet adds mystical depth"
}

Theme: "レトロゲームの歴史"
{
  "primary_color": "neon pink",
  "secondary_color": "acid yellow",
  "mood": "retro-tech nostalgia",
  "reasoning": "Pink and yellow evoke 80s arcade aesthetics and vintage CRT displays"
}
"""
    
    def __init__(self, config: AppConfig):
        """Initialize palette generator
        
        Args:
            config: Application configuration
        """
        self.config = config
        
        api_key = config.env.gemini_api_key
        if not api_key:
            raise ValueError("GEMINI_API_KEY not set")
        
        self.client = genai.Client(api_key=api_key)
        
        # Use Gemini Flash for fast, low-cost palette generation
        gemini_config = getattr(config.yaml.script_generator, "gemini", None)
        self.model_name = getattr(gemini_config, "flash_model", "gemini-2.0-flash-exp") if gemini_config else "gemini-2.0-flash-exp"
        
        logger.info(f"VisualPaletteGenerator initialized with model: {self.model_name}")
    
    async def generate_palette(
        self,
        theme: str,
        script_summary: str
    ) -> VisualPalette:
        """Generate unique color palette for video
        
        Args:
            theme: Video theme
            script_summary: Script summary (200-300 chars)
        
        Returns:
            VisualPalette: Generated color palette
        
        Raises:
            RuntimeError: If generation fails
        """
        logger.info(f"Generating visual palette for theme: {theme}")
        console.print("[cyan]Generating unique color palette for video...[/cyan]")
        console.print(f"[dim]Theme: {theme}[/dim]")
        
        # Build user message
        user_message = f"""Generate a unique color palette for this video:

Theme: {theme}

Summary:
{script_summary[:300]}

Create a visually distinctive palette that captures the essence of this theme."""
        
        try:
            response = await self.client.aio.models.generate_content(
                model=self.model_name,
                contents=[
                    types.Content(
                        role="user",
                        parts=[types.Part(text=self.SYSTEM_PROMPT + "\n\n" + user_message)]
                    )
                ],
                config=types.GenerateContentConfig(
                    temperature=0.9,  # High creativity for diverse palettes
                    max_output_tokens=256,
                    response_mime_type="application/json",
                )
            )
            
            # Parse JSON response
            import json
            palette_data = json.loads(response.text)
            
            palette = VisualPalette(
                primary_color=palette_data["primary_color"],
                secondary_color=palette_data["secondary_color"],
                mood=palette_data["mood"],
                reasoning=palette_data.get("reasoning", "")
            )
            
            logger.info(f"Generated palette: {palette}")
            console.print(f"[green]✓ Palette generated: {palette}[/green]")
            console.print(f"[dim]Reasoning: {palette.reasoning}[/dim]")
            
            return palette
            
        except Exception as e:
            logger.error(f"Palette generation failed: {e}")
            console.print(f"[red]✗ Palette generation failed: {e}[/red]")
            
            # Fallback to default cyberpunk palette
            fallback = self._get_fallback_palette(theme)
            console.print(f"[yellow]Using fallback palette: {fallback}[/yellow]")
            return fallback
    
    def _get_fallback_palette(self, theme: str) -> VisualPalette:
        """Get fallback palette if generation fails
        
        Args:
            theme: Video theme
        
        Returns:
            VisualPalette: Default cyberpunk palette
        """
        return VisualPalette(
            primary_color="electric cyan",
            secondary_color="hot magenta",
            mood="cyberpunk futuristic",
            reasoning=f"Fallback palette for theme: {theme}"
        )
