"""FLUX.1 image generation client for Stable Diffusion WebUI Forge API"""
import base64
import logging
import tempfile
from pathlib import Path

import httpx
from rich.console import Console

from core.models import AppConfig

logger = logging.getLogger(__name__)
console = Console()


class FluxClient:
    """FLUX.1 [schnell] image generation via Forge API
    
    Connects to local Stable Diffusion WebUI Forge instance and generates
    cinematic background images using FLUX.1 [schnell] model.
    """
    
    def __init__(self, config: AppConfig):
        """Initialize FLUX client
        
        Args:
            config: Application configuration
        """
        self.config = config
        flux_config = getattr(config.yaml, "flux", None)
        
        if flux_config:
            self.base_url = flux_config.base_url
            self.timeout = flux_config.timeout
            self.steps = flux_config.steps
            self.width = flux_config.width
            self.height = flux_config.height
            self.sampler_name = flux_config.sampler_name
            self.scheduler = flux_config.scheduler
            self.cfg_scale = flux_config.cfg_scale
        else:
            # Fallback defaults
            self.base_url = "http://127.0.0.1:7890"
            self.timeout = 120
            self.steps = 20
            self.width = 1344
            self.height = 768
            self.sampler_name = "Euler"
            self.scheduler = "Simple"
            self.cfg_scale = 1.0
        
        logger.info(f"FluxClient initialized: {self.base_url}")
    
    async def check_api_status(self) -> bool:
        """Check if Forge API is available
        
        Returns:
            bool: True if API is accessible, False otherwise
        """
        try:
            async with httpx.AsyncClient(timeout=5.0) as client:
                response = await client.get(f"{self.base_url}/sdapi/v1/sd-models")
                if response.status_code == 200:
                    models = response.json()
                    console.print(f"[green]✓ Forge API connected[/green] ({len(models)} models available)")
                    return True
        except Exception as e:
            logger.warning(f"Forge API not available: {e}")
            console.print(f"[yellow]⚠ Forge API not available: {e}[/yellow]")
        return False
    
    async def generate_image(self, prompt: str, output_path: Path) -> Path:
        """Generate image via Forge API
        
        Args:
            prompt: English prompt for image generation
            output_path: Path to save generated image
        
        Returns:
            Path: Path to generated image
        
        Raises:
            RuntimeError: If image generation fails
        """
        # Build payload with FLUX.1 [schnell] golden settings
        payload = {
            "prompt": prompt,
            "negative_prompt": "no text",
            "steps": self.steps,
            "width": self.width,
            "height": self.height,
            "sampler_name": self.sampler_name,
            "scheduler": self.scheduler,
            "cfg_scale": self.cfg_scale,
            "seed": -1,  # Random seed
            "batch_size": 1,
        }
        
        logger.info(f"Generating image: {self.width}x{self.height}, {self.steps} steps")
        console.print(f"[cyan]Generating image via FLUX.1 [schnell]...[/cyan]")
        console.print(f"[dim]Prompt: {prompt[:80]}...[/dim]")
        
        try:
            async with httpx.AsyncClient(timeout=self.timeout) as client:
                response = await client.post(
                    f"{self.base_url}/sdapi/v1/txt2img",
                    json=payload
                )
                response.raise_for_status()
                
                result = response.json()
                
                # Extract first image from response
                images = result.get("images")
                if not images or not isinstance(images, list) or len(images) == 0:
                    raise RuntimeError("No images returned from Forge API")
                
                # Decode base64 image with error handling
                image_b64 = images[0]
                try:
                    image_data = base64.b64decode(image_b64)
                except Exception as e:
                    raise RuntimeError(f"Failed to decode base64 image: {e}")
                
                # Save to output path atomically (prevent race conditions)
                output_path.parent.mkdir(parents=True, exist_ok=True)
                
                # Write to temporary file first, then atomic rename
                with tempfile.NamedTemporaryFile(
                    mode='wb',
                    dir=output_path.parent,
                    delete=False,
                    suffix='.tmp'
                ) as tmp_file:
                    tmp_file.write(image_data)
                    tmp_path = Path(tmp_file.name)
                
                # Atomic rename (replaces existing file if present)
                tmp_path.replace(output_path)
                
                logger.info(f"Image saved: {output_path}")
                console.print(f"[green]✓ Image generated: {output_path.name}[/green]")
                
                return output_path
                
        except httpx.TimeoutException:
            error_msg = f"Forge API timeout after {self.timeout}s"
            logger.error(error_msg)
            console.print(f"[red]✗ {error_msg}[/red]")
            raise RuntimeError(error_msg)
        except httpx.HTTPStatusError as e:
            error_msg = f"Forge API error: {e.response.status_code}"
            logger.error(error_msg)
            console.print(f"[red]✗ {error_msg}[/red]")
            raise RuntimeError(error_msg)
        except Exception as e:
            error_msg = f"Image generation failed: {e}"
            logger.error(error_msg)
            console.print(f"[red]✗ {error_msg}[/red]")
            raise RuntimeError(error_msg)
