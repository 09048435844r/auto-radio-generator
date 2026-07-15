"""Visual palette generator for dynamic color-driven image generation"""
import logging
from typing import Optional

from rich.console import Console

from core.interfaces.llm_port import LLMRequest
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
from services.script_generation.adapters.factory import LLMAdapterFactory

logger = logging.getLogger(__name__)
console = Console()


class VisualPaletteGenerator:
    """LLM-based visual identity generator

    Step 6 (2026-05-12): Mac Studio Proxy (vLLM / Qwen3 系) 経由でテーマごとの
    visual brand (color palette + aesthetic) を生成する。Gemini 直叩きから移行済み。
    
    Note: This class generates VisualIdentity but returns VisualPalette for
    backward compatibility. Use generate_identity() for full VisualIdentity.
    """
    
    SYSTEM_PROMPT = """You are a professional art director and cinematographer.

Your task is to generate a UNIFIED VISUAL BRAND for a video, including both COLOR PALETTE and AESTHETIC STYLE.

REQUIREMENTS:

1. COLOR PALETTE - Select TWO neon colors that:
   - Are VISUALLY DISTINCTIVE and create strong contrast
   - Reflect the video's theme and mood
   - Use RICH, EVOCATIVE descriptors (e.g., "golden amber" NOT "yellow")
   - Examples: "toxic green", "golden amber", "deep violet", "warm coral", "ice blue", "neon pink"
   - READABILITY GUARD (MANDATORY):
     - primary and secondary MUST contrast strongly in both hue and brightness
     - Keep brightness and saturation high enough for clear visibility — NEVER pick
       dark-on-dark, muddy, or washed-out pairs
     - The palette becomes a thumbnail BACKGROUND with title text overlaid on top,
       so legibility of the overall image comes first

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

COLOR DIVERSITY CONSTRAINTS (MANDATORY - HIGHEST PRIORITY):
- The EXAMPLES below illustrate the OUTPUT FORMAT only — do NOT copy their colors
- Reusing the exact color pair of ANY example below is FORBIDDEN
- Always derive a NEW, theme-specific color combination; two different themes
  should receive visibly different palettes

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
  "primary_color": "soft teal",
  "secondary_color": "warm coral",
  "color_mood": "futuristic medical",
  "aesthetic": "Clean Minimalist Modern",
  "visual_keywords": ["clinical", "sterile", "high-tech", "precision"],
  "reasoning": "Medical theme requires a calming clinical teal balanced by a warm, humane accent"
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

        # Step 6 (2026-05-12): Gemini → Mac Studio Proxy (vLLM Qwen3 系)。
        # orchestrator.curator_model を再利用 (Step 5 の ImagePromptGenerator と
        # 同じ選択基準で、軽量タスク用のスロットを共有する)。
        self.model_name = config.yaml.script_generator.orchestrator.curator_model
        self._llm_port = LLMAdapterFactory.create(
            config, "ollama", model_override=self.model_name
        )

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
            # Step 6: Mac Studio Proxy 経由で JSON 出力を取得し、Pydantic で validate。
            # 旧 Gemini Structured Output (response_schema=VisualIdentity) の代替として、
            # response_format="json" + model_validate_json で構造担保する。
            # SYSTEM_PROMPT に JSON フォーマット例 4 件が含まれており Qwen3 系で安定。
            llm_request = LLMRequest(
                system_prompt=self.SYSTEM_PROMPT,
                user_prompt=user_message,
                model=self.model_name,
                max_tokens=1024,
                temperature=0.9,
                response_format="json",
            )
            llm_response = await self._llm_port.generate(llm_request)
            identity = VisualIdentity.model_validate_json(llm_response.content)

            logger.info(f"Generated visual identity: {identity.primary_color}, {identity.secondary_color}")
            console.print(f"[green]✓ Visual identity generated[/green]")
            console.print(f"[dim]Reasoning: {identity.reasoning}[/dim]")

            # 監査用 (2026-07-15): LLM 生成/フォールバックを実行ログから後追いで
            # 切り分けられるよう、採用 identity の主要フィールドを明示記録する。
            # フォールバック時は except 側の logger.warning が対になる。
            logger.info(
                "[VisualPaletteGenerator] Visual identity 採用 (LLM生成): "
                f"{identity.primary_color} × {identity.secondary_color} "
                f"({identity.color_mood}) | {identity.aesthetic}"
                + (f" | reasoning: {identity.reasoning}" if identity.reasoning else "")
            )

            return identity

        except Exception as e:
            logger.error(f"Failed to generate visual identity: {e}")
            logger.debug(f"Theme: {theme}")
            console.print(f"[red]✗ Visual identity generation failed: {e}[/red]")

            # Fallback to default cyberpunk identity
            fallback = self._get_fallback_identity(theme)
            console.print(f"[yellow]Using fallback visual identity: {fallback}[/yellow]")
            # 監査用 (2026-07-15): WARNING は LogFileWriter (PR-C) の root handler
            # 経由でセッションの processing_log.txt にも自動記録されるため、
            # フォールバック発動が実行ログから後追いで判別できる。
            logger.warning(
                "[VisualPaletteGenerator] Visual identity: LLM生成失敗、"
                f"フォールバック配色を使用 (theme={theme}): "
                f"{fallback.primary_color} × {fallback.secondary_color} "
                f"({fallback.color_mood}) | {fallback.aesthetic}"
            )
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
