"""Image prompt generator for FLUX.1 background images"""
import logging
from typing import Optional

from google import genai
from google.genai import types
from rich.console import Console

from core.models import AppConfig
from core.models.curation import ScriptSegment
from core.models.visual import (
    VisualIdentity,
    VisualPalette,
    DEFAULT_PRIMARY_COLOR,
    DEFAULT_SECONDARY_COLOR,
    DEFAULT_AESTHETIC,
)

logger = logging.getLogger(__name__)
console = Console()


class ImagePromptGenerator:
    """LLM-based image prompt generator
    
    Uses Gemini Flash to generate cinematic English prompts for FLUX.1
    based on radio script segment content.
    """
    
    # Default color palette when VisualIdentity is not provided
    # Issue #4 fix: Derive from centralized constants
    DEFAULT_COLOR_PALETTE = f"{DEFAULT_PRIMARY_COLOR} and {DEFAULT_SECONDARY_COLOR} neon lighting"
    
    SYSTEM_PROMPT_TEMPLATE = """You are a professional cinematographer creating narrative-driven shots for AI image generation.

Your task is to generate a detailed English prompt for FLUX.1 image generation based on the given radio script segment.

UNIFIED VISUAL BRAND (MANDATORY - Apply to ALL shots):
- Color Palette: {color_palette}
- Aesthetic: {aesthetic}
- Film Quality: shot on Kodak Portra 400 film, subtle film grain, highly detailed

NARRATIVE GUIDANCE (FLEXIBLE - Interpret creatively):
{composition_guidance}

CREATIVE FREEDOM:
- Camera angles, distances, and framing: YOUR CHOICE based on narrative needs
- Lighting style and mood: YOUR CHOICE to support the emotional tone
- Composition and visual storytelling: YOUR CHOICE to maximize impact

CONSTRAINTS (MANDATORY):
- ALWAYS incorporate the color palette and aesthetic
- ALWAYS end with: "no text"
- ALWAYS include film quality keywords

OUTPUT FORMAT:
Return ONLY the English prompt text, no explanations or additional text.

EXAMPLE OUTPUT:
"A futuristic medical facility with holographic displays, bathed in electric cyan and hot magenta neon glow, Clean Minimalist Modern aesthetic, clinical and sterile atmosphere, shot on Kodak Portra 400 film, subtle film grain, highly detailed, no text"
"""
    
    THUMBNAIL_SYSTEM_PROMPT_TEMPLATE = """You are a professional cinematographer specializing in creating eye-catching YouTube thumbnail backgrounds.

Your task is to generate a detailed English prompt for FLUX.1 that creates a visually striking, attention-grabbing background image.

UNIFIED VISUAL BRAND (MANDATORY):
- Color Palette: {color_palette}
- Aesthetic: {aesthetic}
- Film Quality: shot on Kodak Portra 400 film, subtle film grain, highly detailed

REQUIREMENTS:
- Focus: Create a SYMBOLIC representation of the video's theme
- Impact: Maximum visual impact for thumbnail click-through rate
- Composition: Dynamic, attention-grabbing framing (YOUR CHOICE)
- ALWAYS end with: "no text" (MANDATORY)

OUTPUT FORMAT:
Return ONLY the English prompt text, no explanations.

EXAMPLE:
"A dramatic medical facility with holographic displays showing glucose data, bathed in electric cyan and hot magenta neon glow, Clean Minimalist Modern aesthetic, clinical and high-tech atmosphere, shot on Kodak Portra 400 film, subtle film grain, highly detailed, no text"
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
        visual_identity: Optional[VisualIdentity] = None
    ) -> str:
        """Generate English image prompt from segment content
        
        Args:
            segment: Script segment
            visual_identity: Optional visual identity for brand consistency
        
        Returns:
            str: English prompt for FLUX.1
        """
        # Issue #6 fix: Single parameter for clarity
        identity = visual_identity
        
        # Extract segment context
        segment_context = self._build_segment_context(segment)
        
        # Get composition guidance based on segment type
        composition_guidance = self._get_composition_guidance(segment.segment_type)
        
        # Build color palette and aesthetic descriptions
        # Issue #1 fix: No isinstance check needed (VisualPalette is now an alias)
        if identity:
            color_palette = identity.to_color_fragment()
            aesthetic = identity.to_aesthetic_fragment()
        else:
            # Fallback to default cyberpunk colors
            color_palette = self.DEFAULT_COLOR_PALETTE
            aesthetic = f"{DEFAULT_AESTHETIC} aesthetic"
        
        # Build dynamic system prompt
        system_prompt = self.SYSTEM_PROMPT_TEMPLATE.format(
            color_palette=color_palette,
            aesthetic=aesthetic,
            composition_guidance=composition_guidance
        )
        
        # Build user message
        user_message = f"""Generate a cinematic image prompt for this radio segment:

Segment Type: {segment.segment_type}
Topic: {segment.topic_title or "General discussion"}

Context:
{segment_context}

Generate a prompt that maintains the unified visual brand while telling a visual story."""
        
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
            fallback = self._get_fallback_prompt(segment, identity)
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
        visual_identity: Optional[VisualIdentity] = None
    ) -> str:
        """Generate eye-catching thumbnail background prompt
        
        Args:
            theme: Video theme
            script_summary: Script summary (200-300 chars)
            topic_title: Optional topic title
            visual_identity: Optional visual identity for brand consistency
        
        Returns:
            str: English prompt for FLUX.1 thumbnail background
        """
        # Issue #6 fix: Single parameter for clarity
        identity = visual_identity
        
        # Build color palette and aesthetic descriptions
        # Issue #1 fix: No isinstance check needed (VisualPalette is now an alias)
        if identity:
            color_palette = identity.to_color_fragment()
            aesthetic = identity.to_aesthetic_fragment()
        else:
            # Fallback to default cyberpunk colors
            color_palette = self.DEFAULT_COLOR_PALETTE
            aesthetic = f"{DEFAULT_AESTHETIC} aesthetic"
        
        # Build dynamic system prompt
        system_prompt = self.THUMBNAIL_SYSTEM_PROMPT_TEMPLATE.format(
            color_palette=color_palette,
            aesthetic=aesthetic
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
            fallback = self._get_fallback_thumbnail_prompt(theme, identity)
            console.print(f"[yellow]Using fallback thumbnail prompt[/yellow]")
            return fallback
    
    def _get_composition_guidance(self, segment_type: str) -> str:
        """Get composition guidance based on segment type
        
        Provides mood-based guidance without constraining specific camera angles,
        lighting, or composition. LLM has creative freedom to interpret.
        
        Args:
            segment_type: Segment type (intro, deep_dive, conclusion)
        
        Returns:
            str: Narrative guidance for LLM
        """
        guidance_map = {
            "intro": """- Narrative Role: Scene-setting, establishing context and atmosphere
- Emotional Tone: Inviting, atmospheric, welcoming
- Visual Focus: Overall environment and spatial context
- Suggested Approach: Create a sense of place and introduction""",
            "deep_dive": """- Narrative Role: Investigation, detailed exploration of subject matter
- Emotional Tone: Intense, analytical, focused
- Visual Focus: Specific details, key elements, intricate aspects
- Suggested Approach: Highlight important subjects with emphasis""",
            "conclusion": """- Narrative Role: Reflection, closure, resolution
- Emotional Tone: Contemplative, hopeful, lingering
- Visual Focus: Sense of completion, emotional resonance
- Suggested Approach: Create reflective atmosphere and closure"""
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
        visual_identity: Optional[VisualIdentity] = None
    ) -> str:
        """Get fallback thumbnail prompt if generation fails
        
        Args:
            theme: Video theme
            visual_identity: Optional visual identity
        
        Returns:
            str: Fallback thumbnail prompt
        """
        # Issue #1 fix: No isinstance check needed
        if visual_identity:
            color_desc = visual_identity.to_color_fragment()
            aesthetic_desc = visual_identity.to_aesthetic_fragment()
        else:
            color_desc = self.DEFAULT_COLOR_PALETTE
            aesthetic_desc = f"{DEFAULT_AESTHETIC} aesthetic"
        
        return (
            f"A dramatic scene representing '{theme}', "
            f"bathed in {color_desc}, "
            f"{aesthetic_desc}, "
            f"dynamic composition with depth, "
            f"shot on Kodak Portra 400 film, subtle film grain, highly detailed, no text"
        )
    
    def _get_fallback_prompt(
        self,
        segment: ScriptSegment,
        visual_identity: Optional[VisualIdentity] = None
    ) -> str:
        """Get fallback prompt if generation fails
        
        Args:
            segment: Script segment
            visual_identity: Optional visual identity
        
        Returns:
            str: Fallback prompt
        """
        # Map segment type to generic scene (without specific camera angles)
        scene_map = {
            "intro": "A futuristic radio studio with neon lights and holographic displays",
            "deep_dive": "A research laboratory with glowing screens and data visualizations",
            "conclusion": "A cityscape with neon-lit buildings at dusk",
        }
        
        scene = scene_map.get(segment.segment_type, "A futuristic cityscape")
        
        # Issue #1 fix: No isinstance check needed
        if visual_identity:
            color_desc = visual_identity.to_color_fragment()
            aesthetic_desc = visual_identity.to_aesthetic_fragment()
        else:
            color_desc = self.DEFAULT_COLOR_PALETTE
            aesthetic_desc = f"{DEFAULT_AESTHETIC} aesthetic"
        
        return (
            f"{scene}, bathed in {color_desc}, "
            f"{aesthetic_desc}, "
            f"shot on Kodak Portra 400 film, subtle film grain, highly detailed, no text"
        )
