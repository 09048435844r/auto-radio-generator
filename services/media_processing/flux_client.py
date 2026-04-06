"""FLUX.1 image generation client for Stable Diffusion WebUI Forge API"""
import base64
import json
import logging
import tempfile
from pathlib import Path
from typing import Tuple

import httpx
from rich.console import Console

from core.models import AppConfig
from core.models.generation_metadata import GenerationMetadata

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
    
    async def generate_image(
        self,
        prompt: str,
        output_path: Path,
        context_type: str = "segment",
        segment_id: str = None,
        segment_type: str = None,
        visual_identity: dict = None,
    ) -> Tuple[Path, GenerationMetadata]:
        """Generate image via Forge API and return metadata
        
        Args:
            prompt: English prompt for image generation
            output_path: Path to save generated image
            context_type: Context type ("segment" or "thumbnail")
            segment_id: Optional segment identifier
            segment_type: Optional segment type
            visual_identity: Optional visual identity dict
        
        Returns:
            Tuple[Path, GenerationMetadata]: Generated image path and metadata
        
        Raises:
            RuntimeError: If image generation fails
        """
        # Build payload with FLUX.1 [schnell] golden settings
        payload = {
            "prompt": prompt,
            "negative_prompt": "text, gibberish, fake text, distorted letters, writing, watermark, signature, logo, words, characters, alphabet",
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
        
        import time
        gen_start = time.time()
        
        # Configure timeout with separate connect/read limits
        timeout_config = httpx.Timeout(
            connect=10.0,  # Connection timeout: 10 seconds
            read=self.timeout,  # Read timeout: from config (default 300s)
            write=10.0,  # Write timeout: 10 seconds
            pool=5.0  # Pool timeout: 5 seconds
        )
        
        # Retry logic for timeout exceptions
        max_retries = 2
        last_exception = None
        
        for attempt in range(max_retries):
            try:
                async with httpx.AsyncClient(timeout=timeout_config) as client:
                    response = await client.post(
                        f"{self.base_url}/sdapi/v1/txt2img",
                        json=payload
                    )
                    response.raise_for_status()
                    break  # Success, exit retry loop
            except httpx.TimeoutException as e:
                if attempt < max_retries - 1:
                    logger.warning(f"FLUX.1 timeout on attempt {attempt + 1}/{max_retries}, retrying...")
                    console.print(f"[yellow]⚠ Timeout ({attempt + 1}/{max_retries}), retrying...[/yellow]")
                    continue
                else:
                    # Final attempt failed
                    error_msg = f"Forge API timeout after {self.timeout}s (all {max_retries} attempts failed)"
                    logger.error(error_msg)
                    console.print(f"[red]✗ {error_msg}[/red]")
                    raise RuntimeError(error_msg) from e
            except httpx.HTTPStatusError as e:
                # Non-timeout HTTP errors: fail immediately
                error_msg = f"Forge API error: {e.response.status_code}"
                logger.error(error_msg)
                console.print(f"[red]✗ {error_msg}[/red]")
                raise RuntimeError(error_msg) from e
            except Exception as e:
                # Other errors: fail immediately
                error_msg = f"Image generation failed: {e}"
                logger.error(error_msg)
                console.print(f"[red]✗ {error_msg}[/red]")
                raise RuntimeError(error_msg) from e
        
        try:
                
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
                
                gen_time = time.time() - gen_start
                
                logger.info(f"Image saved: {output_path}")
                console.print(f"[green]✓ Image generated: {output_path.name}[/green]")
                
                # Extract actual seed from API response
                actual_seed = self._extract_seed_from_response(result)
                
                # Build metadata
                metadata = self._build_metadata(
                    image_path=str(output_path),
                    context_type=context_type,
                    segment_id=segment_id,
                    segment_type=segment_type,
                    prompt=prompt,
                    visual_identity=visual_identity or {},
                    seed=actual_seed,
                    generation_time_sec=gen_time,
                )
                
                return output_path, metadata
        except Exception as e:
            # Catch any errors during image processing (after successful API call)
            error_msg = f"Image processing failed: {e}"
            logger.error(error_msg)
            console.print(f"[red]✗ {error_msg}[/red]")
            raise RuntimeError(error_msg) from e
    
    def _extract_seed_from_response(self, response_data: dict) -> int:
        """Extract actual seed value from Forge API response
        
        Args:
            response_data: Full API response dict
        
        Returns:
            int: Actual seed used (-1 if extraction fails)
        """
        try:
            # Forge API returns 'info' as a JSON string
            info_str = response_data.get("info", "")
            if not info_str:
                logger.warning("No 'info' field in Forge API response, using seed=-1")
                return -1
            
            # Parse info JSON
            info_data = json.loads(info_str)
            
            # Extract seed
            seed = info_data.get("seed", -1)
            
            if seed == -1:
                logger.warning("No 'seed' field in Forge API info, using seed=-1")
            else:
                logger.debug(f"Extracted actual seed from Forge API: {seed}")
            
            return seed
            
        except json.JSONDecodeError as e:
            logger.warning(f"Failed to parse Forge API 'info' field: {e}, using seed=-1")
            return -1
        except Exception as e:
            logger.warning(f"Unexpected error extracting seed: {e}, using seed=-1")
            return -1
    
    def _build_metadata(
        self,
        image_path: str,
        context_type: str,
        segment_id: str,
        segment_type: str,
        prompt: str,
        visual_identity: dict,
        seed: int,
        generation_time_sec: float,
    ) -> GenerationMetadata:
        """Build GenerationMetadata from generation parameters
        
        Args:
            image_path: Path to generated image
            context_type: Context type
            segment_id: Segment identifier
            segment_type: Segment type
            prompt: Full prompt
            visual_identity: Visual identity dict
            seed: Actual seed used
            generation_time_sec: Generation time
        
        Returns:
            GenerationMetadata: Metadata instance
        """
        resolution = f"{self.width}x{self.height}"
        
        if context_type == "segment":
            return GenerationMetadata.create_from_segment(
                image_path=image_path,
                segment_id=segment_id,
                segment_type=segment_type,
                prompt=prompt,
                visual_identity=visual_identity,
                seed=seed,
                generation_time_sec=generation_time_sec,
                resolution=resolution,
                steps=self.steps,
                sampler=self.sampler_name,
                cfg_scale=self.cfg_scale,
            )
        else:
            return GenerationMetadata.create_from_thumbnail(
                image_path=image_path,
                prompt=prompt,
                visual_identity=visual_identity,
                seed=seed,
                generation_time_sec=generation_time_sec,
                resolution=resolution,
                steps=self.steps,
                sampler=self.sampler_name,
                cfg_scale=self.cfg_scale,
            )
