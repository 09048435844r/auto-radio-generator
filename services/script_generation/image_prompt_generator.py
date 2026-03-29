"""Image prompt generator for FLUX.1 background images"""
import logging
from typing import Optional

from google import genai
from google.genai import types
from rich.console import Console

from core.models import AppConfig
from core.models.curation import ScriptSegment

logger = logging.getLogger(__name__)
console = Console()


class ImagePromptGenerator:
    """LLM-based image prompt generator
    
    Uses Gemini Flash to generate cinematic English prompts for FLUX.1
    based on radio script segment content.
    """
    
    SYSTEM_PROMPT = """You are a professional cinematographer and photographer specializing in creating cinematic wide shots for AI image generation.

Your task is to generate a detailed English prompt for FLUX.1 image generation based on the given radio script segment.

REQUIREMENTS:
- Style: vaporwave / cyberpunk aesthetic
- Shot type: cinematic wide shot, 35mm lens, shallow depth of field
- Lighting: dramatic cinematic lighting, neon reflections, chiaroscuro
- Film quality: shot on Kodak Portra 400 film, subtle film grain, highly detailed
- ALWAYS end with: "no text"

OUTPUT FORMAT:
Return ONLY the English prompt text, no explanations or additional text.

EXAMPLE OUTPUT:
"A futuristic cyberpunk cityscape at night, neon-lit skyscrapers reflecting in rain-soaked streets, cinematic wide shot, 35mm lens, shallow depth of field, dramatic cinematic lighting, neon reflections, chiaroscuro, shot on Kodak Portra 400 film, subtle film grain, highly detailed, no text"
"""
    
    def __init__(self, config: AppConfig):
        """Initialize prompt generator
        
        Args:
            config: Application configuration
        """
        self.config = config
        
        api_key = config.env.gemini_api_key
        if not api_key:
            raise ValueError("GEMINI_API_KEY not set")
        
        self.client = genai.Client(api_key=api_key)
        
        # Use Gemini Flash for fast, low-cost prompt generation
        gemini_config = getattr(config.yaml.script_generator, "gemini", None)
        self.model_name = gemini_config.flash_model if gemini_config else "gemini-2.0-flash-exp"
        
        logger.info(f"ImagePromptGenerator initialized with model: {self.model_name}")
    
    async def generate_prompt(self, segment: ScriptSegment) -> str:
        """Generate English image prompt from segment content
        
        Args:
            segment: Script segment
        
        Returns:
            str: English prompt for FLUX.1
        """
        # Extract segment context
        segment_context = self._build_segment_context(segment)
        
        # Build user message
        user_message = f"""Generate a cinematic image prompt for this radio segment:

Segment Type: {segment.segment_type}
Topic: {segment.topic_title or "General discussion"}

Context:
{segment_context}

Generate a vaporwave/cyberpunk aesthetic prompt following the requirements."""
        
        logger.info(f"Generating prompt for segment: {segment.segment_id}")
        console.print(f"[cyan]Generating image prompt for {segment.segment_id}...[/cyan]")
        
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
                    temperature=0.8,
                    max_output_tokens=256,
                )
            )
            
            prompt = response.text.strip()
            
            # Ensure "no text" is at the end
            if "no text" not in prompt.lower():
                prompt += ", no text"
            
            logger.info(f"Generated prompt: {prompt[:100]}...")
            console.print(f"[dim]Prompt: {prompt[:80]}...[/dim]")
            
            return prompt
            
        except Exception as e:
            logger.error(f"Prompt generation failed: {e}")
            console.print(f"[red]✗ Prompt generation failed: {e}[/red]")
            
            # Fallback to generic prompt
            fallback = self._get_fallback_prompt(segment)
            console.print(f"[yellow]Using fallback prompt[/yellow]")
            return fallback
    
    def _build_segment_context(self, segment: ScriptSegment) -> str:
        """Build context string from segment
        
        Args:
            segment: Script segment
        
        Returns:
            str: Context description
        """
        context_parts = []
        
        # Add topic if available
        if segment.topic_title:
            context_parts.append(f"Topic: {segment.topic_title}")
        
        # Add sample dialogue if available
        if segment.turns and len(segment.turns) > 0:
            # Get first few turns as context (turns are dicts)
            sample_turns = segment.turns[:3]
            dialogue_sample = " ".join([
                turn.get("text", "") for turn in sample_turns 
                if turn.get("text")
            ])
            if dialogue_sample:
                context_parts.append(f"Discussion: {dialogue_sample[:200]}...")
        
        return "\n".join(context_parts) if context_parts else "General radio discussion"
    
    def _get_fallback_prompt(self, segment: ScriptSegment) -> str:
        """Get fallback prompt if generation fails
        
        Args:
            segment: Script segment
        
        Returns:
            str: Fallback prompt
        """
        # Map segment type to generic scene
        scene_map = {
            "intro": "A futuristic radio studio with neon lights and holographic displays",
            "deep_dive": "A cyberpunk research laboratory with glowing screens and data visualizations",
            "conclusion": "A vaporwave sunset cityscape with neon-lit buildings",
        }
        
        scene = scene_map.get(segment.segment_type, "A cyberpunk cityscape at night")
        
        return (
            f"{scene}, cinematic wide shot, 35mm lens, shallow depth of field, "
            f"dramatic cinematic lighting, neon reflections, chiaroscuro, "
            f"shot on Kodak Portra 400 film, subtle film grain, highly detailed, no text"
        )
