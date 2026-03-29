# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.0.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

### Fixed
- **Video truncation issue**: Fixed video ending 5 seconds early due to post-roll not being included in segment timing calculations
  - Modified `services/audio_synthesis/voicevox_segment_timing.py` to add post-roll duration (5s) to the last segment
  - Video duration now matches audio duration exactly (e.g., 497.6s audio → 497.6s video instead of 478.1s)
  - Resolves issue where audio would cut off abruptly at the end of videos
  
- **FLUX.1 timeout issues**: Optimized FLUX.1 image generation settings for low VRAM environments
  - Increased timeout from 120s to 300s to handle GPU performance degradation
  - Reduced inference steps from 20 to 10 (FLUX.1 schnell performs well with 4-10 steps)
  - Lowered resolution from 1344×768 to 1024×576 (50% VRAM reduction, maintains 16:9 aspect ratio)
  - Expected processing time improvement: 211s → 50-60s per image
  - Modified `config.yaml` FLUX settings with detailed comments explaining optimizations
  
- **Dynamic mode fallback failure**: Fixed ImageProvider not scanning static images when in dynamic mode
  - Modified `services/media_processing/image_provider.py` to always scan static images regardless of mode
  - Enables automatic fallback to static images when FLUX.1 generation fails or times out
  - Prevents "No background images found" errors during fallback

### Refactored
- **Visual Palette architecture cleanup**: Improved code quality and maintainability of visual identity system
  - Fixed critical type annotation bugs (`Any` import missing, `any` → `Any` corrections)
  - Moved palette generation from Phase 2.5 into `execute_scripting_phase` for proper async context
  - Eliminated post-hoc mutation of `ScriptingPhaseResult` to maintain data immutability
  - Extracted duplicate fallback color strings to `DEFAULT_COLOR_PALETTE` class constant (DRY principle)
  - Updated error messages to accurately reflect actual behavior (fallback to component defaults)
  - All changes verified with `python -m py_compile` for syntax correctness

## [3.5.0] - 2026-02-15

### Added
- Hierarchical Agentic Workflow for long-form script generation
- Topic curation with multi-dimensional scoring
- Segment-based generation (intro/deep_dive/conclusion)
- Context continuity across segments

## [3.4.0] - 2026-01-XX

### Added
- Multi-LLM provider support (Gemini/OpenAI/Anthropic)
- Factory pattern for provider selection
- OpenAI Structured Outputs integration
- Anthropic Tool Calling integration

## [3.3.2] - 2025-12-XX

### Added
- Two-part episode mode
- API health check functionality
- Automatic speaker swap detection and correction
- Retry logic for API failures

## [3.3.1] - 2025-12-XX

### Added
- Perplexity API call hard limit
- Session-based research result caching

## [3.3.0] - 2025-11-XX

### Added
- Negative prompt (avoid topics) functionality
- Loudness normalization (-14 LUFS)
- Visual progress bar with Gradio
- Mock mode for development
- NVENC GPU acceleration

## [3.2.0] - 2025-10-XX

### Added
- Initial release with core functionality
- Perplexity research integration
- Gemini script generation
- VOICEVOX audio synthesis
- FFmpeg video rendering
- Thumbnail generation
