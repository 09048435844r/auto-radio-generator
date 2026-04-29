"""FLUX.1 integration test script

Tests the complete FLUX.1 dynamic background generation pipeline:
1. Forge API connection
2. Prompt generation from segment
3. End-to-end image generation
"""
import asyncio
from pathlib import Path

from rich.console import Console

from core.models.config import load_config
from core.models.curation import ScriptSegment
from core.models.script import DialogueTurn
from services.media_processing import FluxClient, ImageProvider
from services.script_generation.image_prompt_generator import ImagePromptGenerator

console = Console()


async def test_flux_api():
    """Test Forge API connection"""
    console.print("\n[bold cyan]Test 1: Forge API Connection[/bold cyan]")
    console.print("=" * 60)
    
    try:
        config = load_config()
        client = FluxClient(config)
        
        status = await client.check_api_status()
        
        if status:
            console.print("[green]✓ Forge API is available[/green]")
            return True
        else:
            console.print("[red]✗ Forge API is not available[/red]")
            console.print("[yellow]Please ensure Stable Diffusion WebUI Forge is running at http://127.0.0.1:7890[/yellow]")
            return False
    except Exception as e:
        console.print(f"[red]✗ Error: {e}[/red]")
        return False


async def test_prompt_generation():
    """Test prompt generation"""
    console.print("\n[bold cyan]Test 2: Prompt Generation[/bold cyan]")
    console.print("=" * 60)
    
    try:
        config = load_config()
        generator = ImagePromptGenerator(config)
        
        # Create mock segment with sample dialogue
        segment = ScriptSegment(
            segment_id="deep_dive_1",
            segment_type="deep_dive",
            topic_title="持続血糖測定器CGMについて",
            turns=[
                DialogueTurn(speaker="A", text="今日は持続血糖測定器について話しましょう", turn_type="dialogue").model_dump(),
                DialogueTurn(speaker="B", text="CGMは糖尿病管理の革新的なデバイスですね", turn_type="dialogue").model_dump(),
            ]
        )
        
        console.print(f"[dim]Segment: {segment.segment_id}[/dim]")
        console.print(f"[dim]Topic: {segment.topic_title}[/dim]")
        
        prompt = await generator.generate_prompt(segment)
        
        console.print(f"\n[green]✓ Prompt generated successfully[/green]")
        console.print(f"\n[bold]Generated Prompt:[/bold]")
        console.print(f"[yellow]{prompt}[/yellow]")
        
        return True
    except Exception as e:
        console.print(f"[red]✗ Error: {e}[/red]")
        return False


async def test_image_generation():
    """Test end-to-end image generation"""
    console.print("\n[bold cyan]Test 3: End-to-End Image Generation[/bold cyan]")
    console.print("=" * 60)
    
    config = None
    original_mode = None
    
    try:
        config = load_config()
        
        # Temporarily override to dynamic mode for testing
        # background_mode is in video_renderer section of config.yaml
        if not hasattr(config.yaml.video_renderer, "background_mode"):
            # Add the attribute dynamically for testing
            config.yaml.video_renderer.__dict__["background_mode"] = "dynamic"
            original_mode = None  # Don't restore if we added it
        else:
            original_mode = config.yaml.video_renderer.background_mode
            config.yaml.video_renderer.background_mode = "dynamic"
        
        provider = ImageProvider(config)
        
        # Create mock segment
        segment = ScriptSegment(
            segment_id="intro",
            segment_type="intro",
            topic_title="ラジオ番組のオープニング",
            turns=[
                DialogueTurn(speaker="A", text="こんにちは、今日も始まりました", turn_type="dialogue").model_dump(),
            ]
        )
        
        console.print(f"[dim]Generating image for segment: {segment.segment_id}[/dim]")
        
        image_path = await provider.get_image_for_segment(segment)
        
        console.print(f"\n[green]✓ Image generated successfully[/green]")
        console.print(f"[bold]Image Path:[/bold] {image_path}")
        console.print(f"[bold]File Size:[/bold] {image_path.stat().st_size / 1024:.1f} KB")
        
        return True
        
    except Exception as e:
        console.print(f"[red]✗ Error: {e}[/red]")
        return False
    
    finally:
        # Restore original mode if needed
        if config and original_mode is not None:
            try:
                config.yaml.video_renderer.background_mode = original_mode
            except:
                pass  # Ignore restoration errors


async def main():
    """Run all tests"""
    console.print("[bold magenta]FLUX.1 Integration Test Suite[/bold magenta]")
    console.print("[dim]Testing dynamic background image generation pipeline[/dim]\n")
    
    results = []
    
    # Test 1: API Connection
    result1 = await test_flux_api()
    results.append(("Forge API Connection", result1))
    
    if not result1:
        console.print("\n[yellow]⚠ Skipping remaining tests (Forge API not available)[/yellow]")
        console.print("\n[bold]Setup Instructions:[/bold]")
        console.print("1. Start Stable Diffusion WebUI Forge")
        console.print("2. Ensure FLUX.1 [schnell] model is loaded")
        console.print("3. Verify API is accessible at http://127.0.0.1:7890")
        return
    
    # Test 2: Prompt Generation
    result2 = await test_prompt_generation()
    results.append(("Prompt Generation", result2))
    
    # Test 3: Image Generation
    result3 = await test_image_generation()
    results.append(("Image Generation", result3))
    
    # Summary
    console.print("\n" + "=" * 60)
    console.print("[bold]Test Summary[/bold]")
    console.print("=" * 60)
    
    for test_name, result in results:
        status = "[green]✓ PASS[/green]" if result else "[red]✗ FAIL[/red]"
        console.print(f"{test_name}: {status}")
    
    all_passed = all(r for _, r in results)
    
    if all_passed:
        console.print("\n[bold green]All tests passed! FLUX.1 integration is ready.[/bold green]")
        console.print("\n[bold]Next Steps:[/bold]")
        console.print("1. Set background_mode: 'dynamic' in config.yaml")
        console.print("2. Run main.py to generate a video with dynamic backgrounds")
        console.print("3. Check output/.image_cache/ for generated images")
    else:
        console.print("\n[bold red]Some tests failed. Please check the errors above.[/bold red]")


if __name__ == "__main__":
    asyncio.run(main())
