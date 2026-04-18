"""Visual palette generator for dynamic color-driven image generation"""
import json
import logging
from typing import Optional

from google import genai
from google.genai import types
from rich.console import Console

from core.models import AppConfig
from core.models.visual import (
    VisualIdentity,
    VisualPalette,
    DEFAULT_PRIMARY_COLOR,
    DEFAULT_SECONDARY_COLOR,
    DEFAULT_COLOR_MOOD,
    DEFAULT_AESTHETIC,
    DEFAULT_VISUAL_KEYWORDS,
)

logger = logging.getLogger(__name__)
console = Console()


class VisualPaletteGenerator:
    """LLM-based visual identity generator
    
    Uses Gemini Flash to generate a unique visual brand (color palette + aesthetic)
    for each video, ensuring visual consistency across all segments and thumbnail.
    
    Note: This class generates VisualIdentity but returns VisualPalette for
    backward compatibility. Use generate_identity() for full VisualIdentity.
    """
    
    SYSTEM_PROMPT = """You are a professional art director and cinematographer.

Your task is to generate a UNIFIED VISUAL BRAND for a video, including both COLOR PALETTE and AESTHETIC STYLE.

REQUIREMENTS:

1. COLOR PALETTE - Select TWO neon colors that:
   - Are VISUALLY DISTINCTIVE and create strong contrast
   - Reflect the video's theme and mood
   - Use RICH, EVOCATIVE descriptors (e.g., "electric cyan" NOT "blue")
   - Examples: "electric cyan", "hot magenta", "toxic green", "neon pink", "acid yellow"

2. COLOR MOOD - Capture the color-based atmosphere in 2-4 words:
   - Examples: "futuristic medical", "warm nostalgic", "mysterious paranormal"

3. AESTHETIC STYLE - Choose ONE primary aesthetic that fits the theme:
   - Clean Minimalist Modern (clinical, professional, high-tech)
   - Cozy Lo-fi Studio (warm, analog, intimate)
   - Dystopian Industrial (gritty, mechanical, harsh)
   - Retro Arcade (pixelated, CRT glow, nostalgic)
   - Clinical Futuristic (sterile, precision, advanced)
   - Neon Cyberpunk (urban, neon-lit, futuristic)
   - Warm Analog (vintage, film grain, organic)
   - Or create your own that fits the theme

4. VISUAL KEYWORDS - Provide 3-5 keywords defining the aesthetic:
   - Examples: ["clinical", "sterile", "high-tech"], ["warm", "vintage", "cozy"]

OUTPUT FORMAT (JSON):
{
  "primary_color": "<rich color descriptor>",
  "secondary_color": "<rich color descriptor>",
  "color_mood": "<2-4 word color atmosphere>",
  "aesthetic": "<aesthetic style name>",
  "visual_keywords": ["<keyword1>", "<keyword2>", "<keyword3>"],
  "reasoning": "<brief explanation>"
}

EXAMPLES:

Theme: "持続血糖測定器CGMについて"
{
  "primary_color": "electric cyan",
  "secondary_color": "hot magenta",
  "color_mood": "futuristic medical",
  "aesthetic": "Clean Minimalist Modern",
  "visual_keywords": ["clinical", "sterile", "high-tech", "precision"],
  "reasoning": "Medical theme requires clean, professional aesthetic with tech-forward colors"
}

Theme: "都市伝説の真相"
{
  "primary_color": "toxic green",
  "secondary_color": "deep violet",
  "color_mood": "mysterious paranormal",
  "aesthetic": "Dystopian Industrial",
  "visual_keywords": ["gritty", "dark", "ominous", "urban decay"],
  "reasoning": "Urban legends call for dark, mysterious aesthetic with supernatural colors"
}

Theme: "レトロゲームの歴史"
{
  "primary_color": "neon pink",
  "secondary_color": "acid yellow",
  "color_mood": "retro-tech nostalgia",
  "aesthetic": "Retro Arcade",
  "visual_keywords": ["pixelated", "CRT glow", "80s arcade", "vintage"],
  "reasoning": "Retro gaming theme calls for warm nostalgic colors and arcade aesthetic"
}

Theme: "Lo-fiヒップホップの魅力"
{
  "primary_color": "warm amber",
  "secondary_color": "soft violet",
  "color_mood": "cozy nostalgic",
  "aesthetic": "Cozy Lo-fi Studio",
  "visual_keywords": ["warm", "analog", "intimate", "vinyl texture"],
  "reasoning": "Lo-fi music requires warm, intimate aesthetic with analog feel"
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
        self.model_name = getattr(gemini_config, "flash_model", "gemini-3-flash-preview") if gemini_config else "gemini-3-flash-preview"
        
        logger.info(f"VisualPaletteGenerator initialized with model: {self.model_name}")
    
    async def generate_identity(
        self,
        theme: str,
        script_summary: str
    ) -> VisualIdentity:
        """Generate unique visual identity (color palette + aesthetic) for video
        
        Args:
            theme: Video theme
            script_summary: Script summary (200-300 chars)
        
        Returns:
            VisualIdentity: Generated visual identity
        
        Raises:
            RuntimeError: If generation fails
        """
        logger.info(f"Generating visual identity for theme: {theme}")
        console.print("[cyan]Generating unique visual brand (color + aesthetic) for video...[/cyan]")
        console.print(f"[dim]Theme: {theme}[/dim]")
        
        # Build user message
        user_message = f"""Generate a unified visual brand for this video:

Theme: {theme}

Summary:
{script_summary[:300]}

Create a visually distinctive brand (color palette + aesthetic) that captures the essence of this theme."""
        
        try:
            import asyncio
            
            prompt_text = self.SYSTEM_PROMPT + "\n\n" + user_message
            
            # Run sync client in a thread to avoid blocking the event loop.
            # asyncio.wait_for only works reliably with asyncio.to_thread (not aio client).
            #
            # Root-cause fix for "Unterminated string" JSONDecodeError:
            # - Use Structured Output (response_schema=VisualIdentity) so the SDK
            #   returns a parsed Pydantic instance and JSON validity is guaranteed
            #   by the model. This removes markdown fence stripping and json.loads.
            # - Set thinking_budget=0 on gemini-3-flash-preview so internal thinking
            #   tokens do not consume the output budget (previous 512-token limit
            #   was being exhausted by ~400 thinking tokens, truncating the JSON).
            # - Keep max_output_tokens generous (1024) as a safety margin.
            def _sync_call():
                return self.client.models.generate_content(
                    model=self.model_name,
                    contents=prompt_text,
                    config=types.GenerateContentConfig(
                        temperature=0.9,
                        max_output_tokens=1024,
                        response_mime_type="application/json",
                        response_schema=VisualIdentity,
                        thinking_config=types.ThinkingConfig(thinking_budget=0),
                    )
                )
            
            response = await asyncio.wait_for(
                asyncio.to_thread(_sync_call),
                timeout=30.0
            )
            
            # Structured Output: SDK returns a parsed Pydantic instance directly.
            identity = response.parsed
            if not isinstance(identity, VisualIdentity):
                # Defensive: fall back to manual parsing if parsed is missing
                # (e.g., empty response due to safety filter or MAX_TOKENS).
                finish_reason = None
                try:
                    finish_reason = response.candidates[0].finish_reason
                except Exception:
                    pass
                raise ValueError(
                    f"Visual identity response missing parsed payload "
                    f"(finish_reason={finish_reason}, text={response.text!r:.200})"
                )
            
            logger.info(f"Generated visual identity: {identity.primary_color}, {identity.secondary_color}")
            console.print(f"[green]✓ Visual identity generated[/green]")
            console.print(f"[dim]Reasoning: {identity.reasoning}[/dim]")
            
            return identity
            
        except Exception as e:
            logger.error(f"Failed to generate visual identity: {e}")
            logger.debug(f"Theme: {theme}")
            console.print(f"[red]✗ Visual identity generation failed: {e}[/red]")
            
            # Fallback to default cyberpunk identity
            fallback = self._get_fallback_identity(theme)
            console.print(f"[yellow]Using fallback visual identity: {fallback}[/yellow]")
            return fallback
    
    async def generate_palette(
        self,
        theme: str,
        script_summary: str
    ) -> VisualPalette:
        """Generate unique color palette for video (backward compatibility wrapper)
        
        This method wraps generate_identity() and returns VisualPalette for
        backward compatibility with existing code.
        
        Args:
            theme: Video theme
            script_summary: Script summary (200-300 chars)
        
        Returns:
            VisualPalette: Generated visual identity as VisualPalette
        
        Raises:
            RuntimeError: If generation fails
        """
        identity = await self.generate_identity(theme, script_summary)
        # VisualPalette is a subclass of VisualIdentity, so this is safe
        return identity
    
    def _get_fallback_identity(self, theme: str) -> VisualIdentity:
        """Get fallback visual identity if generation fails
        
        Args:
            theme: Video theme
        
        Returns:
            VisualIdentity: Default cyberpunk visual identity
        """
        # Issue #4 fix: Use centralized default constants
        return VisualIdentity(
            primary_color=DEFAULT_PRIMARY_COLOR,
            secondary_color=DEFAULT_SECONDARY_COLOR,
            color_mood=DEFAULT_COLOR_MOOD,
            aesthetic=DEFAULT_AESTHETIC,
            visual_keywords=list(DEFAULT_VISUAL_KEYWORDS),  # Convert tuple to list
            reasoning=f"Fallback visual identity for theme: {theme}"
        )
    
    def _get_fallback_palette(self, theme: str) -> VisualPalette:
        """Get fallback palette if generation fails (backward compatibility)
        
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
