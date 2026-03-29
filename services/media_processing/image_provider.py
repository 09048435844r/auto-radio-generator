"""Background image provider for segment-based video rendering

Provides background images for each segment, either by:
1. Static mode: Selecting from local assets (assets/backgrounds/)
2. Dynamic mode: Generating via DALL-E 3 API (future implementation)

Static mode uses segment type to select appropriate images:
- intro_*.png for intro segments
- topic_*.png for deep_dive segments
- conclusion_*.png for conclusion segments
"""
import hashlib
import logging
import random
from pathlib import Path
from typing import Optional

from rich.console import Console

from core.models import AppConfig
from core.models.curation import ScriptSegment

logger = logging.getLogger(__name__)
console = Console()


class ImageProvider:
    """Background image provider
    
    Provides background images for each segment based on configuration.
    Supports static (local assets) and dynamic (DALL-E 3) modes.
    """
    
    def __init__(self, config: AppConfig):
        """Initialize image provider
        
        Args:
            config: Application configuration
        """
        self.config = config
        
        # Get mode from config (default to static)
        video_config = getattr(config.yaml, "video_renderer", None)
        self.mode = getattr(video_config, "background_mode", "static") if video_config else "static"
        
        self.static_images_dir = Path("assets/backgrounds")
        self.cache_dir = Path("output/.image_cache")
        self.cache_dir.mkdir(parents=True, exist_ok=True)
        
        # Scan available static images
        self._static_images: dict[str, list[Path]] = {}
        if self.mode == "static":
            self._scan_static_images()
        
        # Initialize dynamic generation components
        if self.mode == "dynamic":
            from services.script_generation.image_prompt_generator import ImagePromptGenerator
            from services.media_processing.flux_client import FluxClient
            
            self.prompt_generator = ImagePromptGenerator(config)
            self.flux_client = FluxClient(config)
            
            logger.info("Dynamic image generation mode enabled (FLUX.1)")
            console.print("[cyan]Dynamic image generation mode enabled (FLUX.1)[/cyan]")
    
    def _scan_static_images(self):
        """Scan assets/backgrounds/ and categorize by segment type"""
        if not self.static_images_dir.exists():
            logger.warning(f"Backgrounds directory not found: {self.static_images_dir}")
            console.print(f"[yellow]⚠ Backgrounds directory not found: {self.static_images_dir}[/yellow]")
            return
        
        # Scan for images by segment type
        segment_types = ["intro", "deep_dive", "conclusion", "default"]
        
        for seg_type in segment_types:
            pattern = f"{seg_type}_*.png"
            images = list(self.static_images_dir.glob(pattern))
            if images:
                self._static_images[seg_type] = images
                logger.info(f"Found {len(images)} images for segment type '{seg_type}'")
        
        # Also scan for generic images (Abstract_*.png, etc.)
        generic_images = [
            p for p in self.static_images_dir.glob("*.png")
            if not any(p.name.startswith(f"{st}_") for st in segment_types)
        ]
        if generic_images:
            self._static_images["generic"] = generic_images
            logger.info(f"Found {len(generic_images)} generic images")
        
        total_images = sum(len(imgs) for imgs in self._static_images.values())
        console.print(f"[dim]Loaded {total_images} background images from {self.static_images_dir}[/dim]")
    
    async def get_image_for_segment(self, segment: ScriptSegment) -> Path:
        """Get background image for a segment
        
        Args:
            segment: Script segment
        
        Returns:
            Path: Background image path
        """
        if self.mode == "dynamic":
            return await self._generate_dynamic_image(segment)
        else:
            return self._select_static_image(segment)
    
    async def _generate_dynamic_image(self, segment: ScriptSegment) -> Path:
        """Generate background image via FLUX.1
        
        Args:
            segment: Script segment
        
        Returns:
            Path: Generated image path
        """
        # 1. Generate prompt from segment
        prompt = await self.prompt_generator.generate_prompt(segment)
        
        # 2. Check cache (prompt-based key)
        cache_key = self._get_prompt_cache_key(prompt)
        cache_path = self.cache_dir / f"{cache_key}.png"
        
        if cache_path.exists():
            console.print(f"[dim]Using cached image: {cache_path.name}[/dim]")
            logger.info(f"Cache hit for segment {segment.segment_id}")
            return cache_path
        
        # 3. Generate image via FluxClient
        try:
            console.print(f"[cyan]Generating image for {segment.segment_id}...[/cyan]")
            image_path = await self.flux_client.generate_image(prompt, cache_path)
            
            console.print(f"[green]✓ Generated: {image_path.name}[/green]")
            logger.info(f"Image generated for segment {segment.segment_id}: {image_path}")
            
            return image_path
            
        except Exception as e:
            # Fallback to static mode on error
            logger.error(f"Dynamic image generation failed: {e}, falling back to static mode")
            console.print(f"[yellow]⚠ Generation failed, using static fallback[/yellow]")
            return self._select_static_image(segment)
    
    def _select_static_image(self, segment: ScriptSegment) -> Path:
        """Select background image from local assets
        
        Selection strategy:
        1. Try segment type specific images (intro_*.png, etc.)
        2. Fall back to generic images
        3. Use deterministic selection based on segment_id hash
        
        Args:
            segment: Script segment
        
        Returns:
            Path: Selected image path
        
        Raises:
            FileNotFoundError: If no background images are available
        """
        # Map segment type to image category
        segment_type = segment.segment_type
        
        # Try segment-type specific images first
        candidates = self._static_images.get(segment_type, [])
        
        # Fall back to generic images if no type-specific images found
        if not candidates:
            candidates = self._static_images.get("generic", [])
        
        # Fall back to any available images
        if not candidates:
            all_images = []
            for images in self._static_images.values():
                all_images.extend(images)
            candidates = all_images
        
        if not candidates:
            raise FileNotFoundError(
                f"No background images found in {self.static_images_dir}. "
                f"Please add images with naming pattern: {segment_type}_*.png or default_*.png"
            )
        
        # Deterministic selection based on segment_id hash
        # This ensures the same segment always gets the same image
        segment_hash = int(hashlib.md5(segment.segment_id.encode()).hexdigest(), 16)
        selected = candidates[segment_hash % len(candidates)]
        
        logger.debug(f"Selected image for segment '{segment.segment_id}': {selected.name}")
        return selected
    
    def _get_cache_key(self, segment: ScriptSegment) -> str:
        """Generate cache key for a segment
        
        Args:
            segment: Script segment
        
        Returns:
            str: Cache key
        """
        # Use segment_id and topic_title to generate unique key
        content = f"{segment.segment_id}_{segment.topic_title or segment.segment_type}"
        return hashlib.md5(content.encode()).hexdigest()[:16]
    
    def _get_prompt_cache_key(self, prompt: str) -> str:
        """Generate cache key from prompt hash
        
        Args:
            prompt: Image generation prompt
        
        Returns:
            str: Cache key (16-char hex)
        """
        return hashlib.md5(prompt.encode()).hexdigest()[:16]
