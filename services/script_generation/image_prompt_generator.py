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
    
    SYSTEM_PROMPT_TEMPLATE = """You are a professional cinematographer creating SUBJECT-DRIVEN, narrative-focused shots for AI image generation.

Your task is to generate a detailed English prompt for FLUX.1 that visualizes the CONCRETE SUBJECTS discussed in the radio script segment.

PRIMARY FOCUS (MANDATORY - This is your HIGHEST priority):
1. IDENTIFY CONCRETE SUBJECTS from the script:
   - What specific objects, tools, devices, or phenomena are being discussed?
   - What actions, processes, or events are being described?
   - What people, professions, or roles are mentioned?
   - What data, measurements, or visual information is referenced?

2. DESCRIBE SUBJECTS WITH PRECISION:
   - Be SPECIFIC: Instead of "medical facility", describe "a doctor examining a patient's continuous glucose monitor display"
   - Be DETAILED: Instead of "technology", describe "a smartphone app showing real-time blood sugar graphs with trend arrows"
   - Be CONCRETE: Instead of "research", describe "a scientist analyzing DNA sequencing data on multiple screens"

3. START YOUR PROMPT WITH THE SUBJECT:
   - Begin with the most visually representative subject from the script
   - Make the subject the HERO of the composition
   - The subject should occupy the primary visual focus

UNIFIED VISUAL BRAND (MANDATORY - Apply consistently):
- Color Palette: {color_palette}
- Aesthetic: {aesthetic}
- Film Quality: shot on Kodak Portra 400 film, subtle film grain, highly detailed

NARRATIVE GUIDANCE:
{composition_guidance}

CREATIVE FREEDOM:
- Camera angles, distances, and framing: YOUR CHOICE to best showcase the subject
- Lighting style and mood: YOUR CHOICE to support the narrative
- Supporting elements and context: YOUR CHOICE to enrich the scene

CONSTRAINTS (MANDATORY):
- ALWAYS start with a SPECIFIC, CONCRETE subject description (not abstract spaces)
- ALWAYS incorporate the color palette and aesthetic
- ALWAYS end with: "no text, no writing, no watermarks"
- ALWAYS include film quality keywords

OUTPUT FORMAT:
Return ONLY the English prompt text, no explanations.

EXAMPLE OUTPUTS (Subject-Driven):

Example 1 (Medical Topic):
"A doctor in a white coat examining a patient's continuous glucose monitor display showing real-time blood sugar data with trend arrows and alerts, with an insulin pump visible on the patient's belt and medical charts on a tablet nearby, bathed in electric cyan and hot magenta neon glow, Clean Minimalist Modern aesthetic, clinical and high-tech atmosphere, shot on Kodak Portra 400 film, subtle film grain, highly detailed, no text"

Example 2 (Technology Topic):
"A software engineer's hands typing code on a laptop with multiple terminal windows showing AI model training progress bars and loss curves, surrounded by reference books on machine learning and a whiteboard with neural network diagrams, bathed in electric cyan and hot magenta neon glow, Clean Minimalist Modern aesthetic, focused and innovative atmosphere, shot on Kodak Portra 400 film, subtle film grain, highly detailed, no text"

Example 3 (Environmental Topic):
"A climate scientist analyzing satellite imagery of melting ice caps on a large monitor, with data visualization showing temperature anomalies and CO2 concentration graphs, research papers and core sample tubes on the desk, bathed in electric cyan and hot magenta neon glow, Clean Minimalist Modern aesthetic, urgent and analytical atmosphere, shot on Kodak Portra 400 film, subtle film grain, highly detailed, no text"
"""
    
    THUMBNAIL_SYSTEM_PROMPT_TEMPLATE = """You are a professional cinematographer specializing in creating SUBJECT-DRIVEN, eye-catching YouTube thumbnail backgrounds.

Your task is to generate a detailed English prompt for FLUX.1 that creates a visually striking thumbnail featuring CONCRETE SUBJECTS from the video's content.

PRIMARY FOCUS (MANDATORY - Highest priority for click-through rate):
1. IDENTIFY THE MOST ICONIC SUBJECT from the video theme:
   - What is the ONE object, device, person, or phenomenon that best represents this video?
   - What visual element would make viewers immediately understand the topic?
   - What subject would create curiosity and compel clicks?

2. MAKE THE SUBJECT DRAMATIC AND SPECIFIC:
   - Be CONCRETE: Instead of "medical technology", show "a glowing continuous glucose monitor with real-time alerts"
   - Be DYNAMIC: Show the subject in an engaging state (active, illuminated, in use)
   - Be BOLD: The subject should dominate the frame and be instantly recognizable

3. OPTIMIZE FOR THUMBNAIL VISIBILITY:
   - The subject must be clear and identifiable even at small sizes
   - High contrast and visual clarity are essential
   - Avoid cluttered compositions - focus on ONE hero subject

UNIFIED VISUAL BRAND (MANDATORY):
- Color Palette: {color_palette}
- Aesthetic: {aesthetic}
- Film Quality: shot on Kodak Portra 400 film, subtle film grain, highly detailed

REQUIREMENTS:
- Focus: Create a CONCRETE, SUBJECT-DRIVEN representation (not abstract symbolism)
- Impact: Maximum visual impact through clear, bold subject presentation
- Composition: Dynamic framing that showcases the hero subject
- ALWAYS end with: "no text, no writing, no watermarks" (MANDATORY)

OUTPUT FORMAT:
Return ONLY the English prompt text, no explanations.

EXAMPLE OUTPUTS (Subject-Driven Thumbnails):

Example 1 (Medical Topic):
"A close-up of a doctor's hand holding a continuous glucose monitor displaying real-time blood sugar graphs with bright alert indicators, with an insulin pump and medical chart visible in soft focus background, bathed in electric cyan and hot magenta neon glow, Clean Minimalist Modern aesthetic, dramatic and clinical atmosphere, shot on Kodak Portra 400 film, subtle film grain, highly detailed, no text"

Example 2 (Technology Topic):
"A laptop screen showing AI code with glowing syntax highlighting and a neural network visualization diagram, with a programmer's hands on keyboard in dramatic lighting, surrounded by multiple monitors displaying training metrics, bathed in electric cyan and hot magenta neon glow, Clean Minimalist Modern aesthetic, intense and innovative atmosphere, shot on Kodak Portra 400 film, subtle film grain, highly detailed, no text"

Example 3 (Environmental Topic):
"A dramatic satellite image of Earth showing climate data overlays with temperature anomaly heat maps in vivid colors, displayed on a large monitor with a scientist's silhouette analyzing the data, bathed in electric cyan and hot magenta neon glow, Clean Minimalist Modern aesthetic, urgent and impactful atmosphere, shot on Kodak Portra 400 film, subtle film grain, highly detailed, no text"
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
        
        # Build user message with subject-extraction emphasis
        user_message = f"""Generate a SUBJECT-DRIVEN cinematic image prompt for this radio segment.

Segment Type: {segment.segment_type}
Topic: {segment.topic_title or "General discussion"}

Script Content:
{segment_context}

INSTRUCTIONS:
1. Read the script carefully and identify the MOST CONCRETE, VISUALLY REPRESENTATIVE subjects being discussed
2. Choose the subject that best symbolizes the segment's core message
3. Describe that subject with MAXIMUM SPECIFICITY at the start of your prompt
4. Add the unified visual brand (colors, aesthetic, film quality) while keeping the subject as the hero
5. Ensure the final prompt creates an image where viewers immediately understand what the segment is about

Generate the prompt now:"""
        
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
            
            # Ensure "no text, no writing, no watermarks" is at the end
            if "no text" not in prompt.lower():
                prompt += ", no text, no writing, no watermarks"
            
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
        """Build rich context string from segment for subject-driven prompt generation
        
        Provides comprehensive script information to enable LLM to identify
        concrete subjects, objects, and actions discussed in the segment.
        
        Args:
            segment: Script segment
        
        Returns:
            str: Rich context description with full narrative content
        """
        context_parts = []
        
        # Add topic if available
        if segment.topic_title:
            context_parts.append(f"Topic: {segment.topic_title}")
        
        # Add comprehensive dialogue context (expanded from 3 turns to 10+ turns)
        if segment.turns and len(segment.turns) > 0:
            # Strategy: Capture enough turns to convey the segment's core narrative
            # - For short segments (<5 turns): Include all turns
            # - For medium segments (5-15 turns): Include first 10 turns
            # - For long segments (>15 turns): Include first 12 turns + strategic sampling
            
            total_turns = len(segment.turns)
            
            if total_turns <= 5:
                # Short segment: include everything
                sample_turns = segment.turns
            elif total_turns <= 15:
                # Medium segment: first 10 turns capture intro + core discussion
                sample_turns = segment.turns[:10]
            else:
                # Long segment: first 12 turns + sample from middle/end
                # This ensures we capture intro, core points, and conclusion hints
                sample_turns = segment.turns[:12].copy()  # Explicit copy for clarity
                mid_point = total_turns // 2
                # Add 2-3 turns from middle only if they're not already included in first 12
                if mid_point >= 12:
                    sample_turns.extend(segment.turns[mid_point:mid_point+2])
                # Add last 2 turns only if segment is long enough to avoid overlap
                # (total_turns > 14 ensures last 2 turns are beyond first 12)
                if total_turns > 14:
                    sample_turns.extend(segment.turns[-2:])
            
            # Extract dialogue text with generous character limit (800 chars)
            # This allows LLM to grasp concrete subjects and narrative flow
            dialogue_sample = " ".join([
                turn.get("text", "") for turn in sample_turns 
                if turn.get("text")
            ])
            
            if dialogue_sample:
                # Expand character limit from 200 to 800 to preserve narrative richness
                # Truncate gracefully at sentence boundary if needed
                if len(dialogue_sample) > 800:
                    truncated = dialogue_sample[:800]
                    # Try to end at last complete sentence
                    last_period = truncated.rfind('。')
                    if last_period == -1:
                        last_period = truncated.rfind('.')
                    # Use sentence boundary if found and reasonable (not too early)
                    if last_period > 600:
                        truncated = truncated[:last_period + 1]
                    # If no good sentence boundary found, keep full 800 chars (already set)
                    context_parts.append(f"Discussion:\n{truncated}...")
                else:
                    context_parts.append(f"Discussion:\n{dialogue_sample}")
        
        return "\n\n".join(context_parts) if context_parts else "General radio discussion"
    
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

Create a CONCRETE, SUBJECT-DRIVEN representation that maximizes click-through rate."""
        
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
        
        Provides concrete, cinematographer-level directives about which specific
        visual details and subjects to focus on, moving beyond abstract mood to
        actionable visual storytelling instructions.
        
        Args:
            segment_type: Segment type (intro, deep_dive, conclusion)
        
        Returns:
            str: Concrete visual directives for LLM
        """
        guidance_map = {
            "intro": """- Narrative Role: Scene-setting and topic introduction
- Subject Focus: Show the PRIMARY TOOLS, OBJECTS, or SETTING that define this topic
  * For medical topics: Show diagnostic devices, treatment tools, or patient-care equipment
  * For technology topics: Show the core technology, devices, or interfaces being discussed
  * For social topics: Show the people, environments, or artifacts central to the issue
- Visual Details to Emphasize:
  * The main subject should be clearly identifiable and occupy 40-60% of frame
  * Include contextual elements that establish the domain (lab equipment, office setting, etc.)
  * Show the subject in a state of readiness or introduction (not mid-action)
- Suggested Composition: Medium shot or establishing shot that clearly shows what the segment is about""",
            
            "deep_dive": """- Narrative Role: Detailed investigation and analysis
- Subject Focus: Show SPECIFIC PROCESSES, DATA, or ACTIONS being analyzed
  * For medical topics: Show detailed medical procedures, diagnostic data, treatment in action
  * For technology topics: Show code, algorithms, data visualizations, or systems in operation
  * For social topics: Show evidence, statistics, or concrete examples of the phenomenon
- Visual Details to Emphasize:
  * Close-up or detail shots that reveal intricate aspects of the subject
  * Include data, measurements, or visual information mentioned in the script
  * Show active engagement: hands interacting, screens displaying data, processes in motion
  * Multiple related elements can be shown to convey complexity (e.g., multiple monitors, tools in use)
- Suggested Composition: Close-up or medium-close shot emphasizing specific details and active investigation""",
            
            "conclusion": """- Narrative Role: Synthesis and forward-looking perspective
- Subject Focus: Show the OUTCOMES, RESULTS, or FUTURE IMPLICATIONS of the topic
  * For medical topics: Show successful treatment results, patient outcomes, or next-generation tools
  * For technology topics: Show completed systems, deployed solutions, or future prototypes
  * For social topics: Show positive change, solutions in action, or hopeful scenarios
- Visual Details to Emphasize:
  * The subject should convey completion or achievement (finished product, successful result)
  * Include forward-looking elements (next steps, future developments, ongoing monitoring)
  * Show the subject in a state of resolution or continuity (not abandonment)
  * Wider framing that shows the subject in context of its impact or future
- Suggested Composition: Medium or wide shot that shows the subject's place in the larger picture"""
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
        
        # Ensure "no text, no writing, no watermarks" is at the end
        if "no text" not in prompt.lower():
            prompt += ", no text, no writing, no watermarks"
        
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
