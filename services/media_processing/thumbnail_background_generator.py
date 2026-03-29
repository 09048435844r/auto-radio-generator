"""YouTube thumbnail background generator using FLUX.1"""
import logging
from pathlib import Path
from typing import Optional

from rich.console import Console

from core.models import AppConfig
from core.models.visual import VisualPalette
from services.media_processing.flux_client import FluxClient
from services.script_generation.image_prompt_generator import ImagePromptGenerator

logger = logging.getLogger(__name__)
console = Console()


class ThumbnailBackgroundGenerator:
    """FLUX.1-based thumbnail background generator
    
    Generates eye-catching background images for YouTube thumbnails
    based on video theme and script content.
    """
    
    def __init__(self, config: AppConfig):
        """Initialize thumbnail background generator
        
        Args:
            config: Application configuration
        """
        self.config = config
        self.prompt_generator = ImagePromptGenerator(config)
        self.flux_client = FluxClient(config)
    
    async def generate_background(
        self,
        theme: str,
        script_summary: str,
        output_path: Path,
        visual_palette: Optional[VisualPalette] = None,
        topic_title: Optional[str] = None
    ) -> Path:
        """Generate thumbnail background image
        
        Args:
            theme: Video theme
            script_summary: Script summary (200-300 chars)
            output_path: Output path for generated image
            visual_palette: Optional color palette for visual consistency
            topic_title: Optional topic title
        
        Returns:
            Path: Path to generated background image
        
        Raises:
            RuntimeError: If generation fails
        """
        console.print("[cyan]Generating YouTube thumbnail background via FLUX.1...[/cyan]")
        console.print(f"[dim]Theme: {theme}[/dim]")
        if visual_palette:
            console.print(f"[dim]Palette: {visual_palette}[/dim]")
        
        # 1. Generate prompt with palette
        prompt = await self.prompt_generator.generate_thumbnail_prompt(
            theme=theme,
            script_summary=script_summary,
            topic_title=topic_title,
            visual_palette=visual_palette
        )
        
        console.print(f"[dim]Prompt: {prompt[:80]}...[/dim]")
        
        # 2. Generate image via FLUX.1
        image_path = await self.flux_client.generate_image(prompt, output_path)
        
        console.print(f"[green]✓ Thumbnail background generated: {image_path.name}[/green]")
        logger.info(f"Thumbnail background generated: {image_path}")
        
        return image_path
    
    async def check_availability(self) -> bool:
        """Check if FLUX.1 API is available
        
        Returns:
            bool: True if available, False otherwise
        """
        return await self.flux_client.check_api_status()
