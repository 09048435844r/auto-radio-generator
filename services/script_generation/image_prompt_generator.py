"""Image prompt generator for FLUX.1 background images"""
import logging
from typing import Optional

from google import genai
from google.genai import types
from rich.console import Console

from core.models import AppConfig
from core.models.curation import ScriptSegment
from core.models.visual import VisualPalette

logger = logging.getLogger(__name__)
console = Console()


class ImagePromptGenerator:
    """LLM-based image prompt generator
    
    Uses Gemini Flash to generate cinematic English prompts for FLUX.1
    based on radio script segment content.
    """
    
    # Default color palette when VisualPalette is not provided
    DEFAULT_COLOR_PALETTE = "electric cyan and hot magenta neon lighting"
    
    SYSTEM_PROMPT_TEMPLATE = """You are a professional cinematographer creating diverse, narrative-driven shots for AI image generation.

Your task is to generate a detailed English prompt for FLUX.1 image generation based on the given radio script segment.

VISUAL IDENTITY (MANDATORY):
- Color Palette: {color_palette}
- Aesthetic: vaporwave / cyberpunk fusion
- Film Quality: shot on Kodak Portra 400 film, subtle film grain, highly detailed

COMPOSITION GUIDELINES (FLEXIBLE):
{composition_guidance}

OUTPUT FORMAT:
Return ONLY the English prompt text, no explanations or additional text.
ALWAYS end with: "no text"

EXAMPLE OUTPUT:
"A futuristic cyberpunk medical facility with holographic displays, bathed in electric cyan and hot magenta neon glow, aerial establishing shot capturing the vast complex, dawn atmosphere with soft light filtering through, shot on Kodak Portra 400 film, subtle film grain, highly detailed, no text"
"""
    
    THUMBNAIL_SYSTEM_PROMPT_TEMPLATE = """You are a professional cinematographer specializing in creating eye-catching YouTube thumbnail backgrounds.

Your task is to generate a detailed English prompt for FLUX.1 that creates a visually striking, attention-grabbing background image.

VISUAL IDENTITY (MANDATORY):
- Color Palette: {color_palette}
- Aesthetic: vaporwave / cyberpunk fusion
- Film Quality: shot on Kodak Portra 400 film, subtle film grain, highly detailed

REQUIREMENTS:
- Focus: Create a SYMBOLIC representation of the video's theme
- Impact: Maximum visual impact for thumbnail click-through rate
- Composition: Dynamic, attention-grabbing framing
- ALWAYS end with: "no text" (MANDATORY)

OUTPUT FORMAT:
Return ONLY the English prompt text, no explanations.

EXAMPLE:
"A dramatic cyberpunk medical facility with holographic displays showing glucose data, bathed in electric cyan and hot magenta neon glow, dynamic diagonal composition with depth, futuristic health monitoring devices in sharp focus, shot on Kodak Portra 400 film, subtle film grain, highly detailed, no text"
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
        self.model_name = getattr(gemini_config, "flash_model", "gemini-2.0-flash-exp") if gemini_config else "gemini-2.0-flash-exp"
        
        logger.info(f"ImagePromptGenerator initialized with model: {self.model_name}")
    
    async def generate_prompt(
        self,
        segment: ScriptSegment,
        visual_palette: Optional[VisualPalette] = None
    ) -> str:
        """Generate English image prompt from segment content
        
        Args:
            segment: Script segment
            visual_palette: Optional color palette for visual consistency
        
        Returns:
            str: English prompt for FLUX.1
        """
        # Extract segment context
        segment_context = self._build_segment_context(segment)
        
        # Get composition guidance based on segment type
        composition_guidance = self._get_composition_guidance(segment.segment_type)
        
        # Build color palette description
        if visual_palette:
            color_palette = visual_palette.to_prompt_fragment()
        else:
            # Fallback to default cyberpunk colors
            color_palette = self.DEFAULT_COLOR_PALETTE
        
        # Build dynamic system prompt
        system_prompt = self.SYSTEM_PROMPT_TEMPLATE.format(
            color_palette=color_palette,
            composition_guidance=composition_guidance
        )
        
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
                        parts=[types.Part(text=system_prompt + "\n\n" + user_message)]
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
            fallback = self._get_fallback_prompt(segment, visual_palette)
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
    
    async def generate_thumbnail_prompt(
        self,
        theme: str,
        script_summary: str,
        topic_title: Optional[str] = None,
        visual_palette: Optional[VisualPalette] = None
    ) -> str:
        """Generate eye-catching thumbnail background prompt
        
        Args:
            theme: Video theme
            script_summary: Script summary (200-300 chars)
            topic_title: Optional topic title
            visual_palette: Optional color palette for visual consistency
        
        Returns:
            str: English prompt for FLUX.1 thumbnail background
        """
        # Build color palette description
        if visual_palette:
            color_palette = visual_palette.to_prompt_fragment()
        else:
            # Fallback to default cyberpunk colors
            color_palette = self.DEFAULT_COLOR_PALETTE
        
        # Build dynamic system prompt
        system_prompt = self.THUMBNAIL_SYSTEM_PROMPT_TEMPLATE.format(
            color_palette=color_palette
        )
        
        # Build user message
        user_message = f"""Generate a visually striking thumbnail background prompt for this video:

Theme: {theme}
Topic: {topic_title or theme}

Summary:
{script_summary[:300]}

Create a SYMBOLIC, eye-catching representation that maximizes click-through rate."""
        
        logger.info(f"Generating thumbnail prompt for theme: {theme}")
        console.print(f"[cyan]Generating thumbnail background prompt...[/cyan]")
        
        try:
            response = await self.client.aio.models.generate_content(
                model=self.model_name,
                contents=[
                    types.Content(
                        role="user",
                        parts=[types.Part(text=system_prompt + "\n\n" + user_message)]
                    )
                ],
                config=types.GenerateContentConfig(
                    temperature=0.9,  # Higher creativity for thumbnails
                    max_output_tokens=256,
                )
            )
            
            prompt = response.text.strip()
            
            # Enforce mandatory quality keywords only
            prompt = self._enforce_quality_keywords(prompt)
            
            logger.info(f"Generated thumbnail prompt: {prompt[:100]}...")
            console.print(f"[dim]Thumbnail prompt: {prompt[:80]}...[/dim]")
            
            return prompt
            
        except Exception as e:
            logger.error(f"Thumbnail prompt generation failed: {e}")
            console.print(f"[red]✗ Thumbnail prompt generation failed: {e}[/red]")
            
            # Fallback to generic thumbnail prompt
            fallback = self._get_fallback_thumbnail_prompt(theme, visual_palette)
            console.print(f"[yellow]Using fallback thumbnail prompt[/yellow]")
            return fallback
    
    def _get_composition_guidance(self, segment_type: str) -> str:
        """Get composition guidance based on segment type
        
        Args:
            segment_type: Segment type (intro, deep_dive, conclusion)
        
        Returns:
            str: Composition guidance for LLM
        """
        guidance_map = {
            "intro": """- Camera: Wide establishing shot, aerial or distant perspective to set the scene
- Mood: Inviting, atmospheric, scene-setting
- Time: Dawn or dusk lighting for dramatic introduction
- Focus: Capture the overall environment and context""",
            "deep_dive": """- Camera: Medium to close-up shots, focus on specific details and subjects
- Mood: Intense, investigative, analytical
- Lighting: Focused spotlights, high contrast for emphasis
- Focus: Highlight key elements and intricate details""",
            "conclusion": """- Camera: Pull-back to wide shot, reflective perspective
- Mood: Contemplative, hopeful, lingering atmosphere
- Time: Sunset or night for emotional resonance
- Focus: Create sense of closure and reflection"""
        }
        return guidance_map.get(segment_type, guidance_map["deep_dive"])
    
    def _enforce_quality_keywords(self, prompt: str) -> str:
        """Enforce mandatory quality keywords only (minimal constraints)
        
        Args:
            prompt: Generated prompt
        
        Returns:
            str: Prompt with quality keywords enforced
        """
        # Only enforce film quality keywords, not composition/lighting
        mandatory_quality_keywords = [
            "shot on Kodak Portra 400 film",
            "subtle film grain",
            "highly detailed"
        ]
        
        # Add missing quality keywords
        for keyword in mandatory_quality_keywords:
            if keyword.lower() not in prompt.lower():
                prompt += f", {keyword}"
        
        # Ensure "no text" is at the end
        if "no text" not in prompt.lower():
            prompt += ", no text"
        
        return prompt
    
    def _get_fallback_thumbnail_prompt(
        self,
        theme: str,
        visual_palette: Optional[VisualPalette] = None
    ) -> str:
        """Get fallback thumbnail prompt if generation fails
        
        Args:
            theme: Video theme
            visual_palette: Optional color palette
        
        Returns:
            str: Fallback thumbnail prompt
        """
        color_desc = visual_palette.to_prompt_fragment() if visual_palette else self.DEFAULT_COLOR_PALETTE
        
        return (
            f"A dramatic cyberpunk scene representing '{theme}', "
            f"neon-lit futuristic environment with holographic displays, "
            f"bathed in {color_desc}, "
            f"dynamic composition with depth, "
            f"shot on Kodak Portra 400 film, subtle film grain, highly detailed, no text"
        )
    
    def _get_fallback_prompt(
        self,
        segment: ScriptSegment,
        visual_palette: Optional[VisualPalette] = None
    ) -> str:
        """Get fallback prompt if generation fails
        
        Args:
            segment: Script segment
            visual_palette: Optional color palette
        
        Returns:
            str: Fallback prompt
        """
        # Map segment type to generic scene
        scene_map = {
            "intro": "A futuristic radio studio with neon lights and holographic displays, wide establishing shot",
            "deep_dive": "A cyberpunk research laboratory with glowing screens and data visualizations, close-up focused view",
            "conclusion": "A vaporwave sunset cityscape with neon-lit buildings, pull-back reflective shot",
        }
        
        scene = scene_map.get(segment.segment_type, "A cyberpunk cityscape at night")
        color_desc = visual_palette.to_prompt_fragment() if visual_palette else self.DEFAULT_COLOR_PALETTE
        
        return (
            f"{scene}, bathed in {color_desc}, "
            f"shot on Kodak Portra 400 film, subtle film grain, highly detailed, no text"
        )
