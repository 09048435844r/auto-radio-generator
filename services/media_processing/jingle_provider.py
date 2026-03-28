"""Jingle provider for segment boundary audio effects

Provides random selection of jingle audio files from assets/jingles/ directory.
Jingles are short audio clips (2-5 seconds) inserted at segment boundaries
to create smooth transitions and enhance production quality.
"""
import logging
from pathlib import Path
from typing import Optional

from pydub import AudioSegment
from rich.console import Console

logger = logging.getLogger(__name__)
console = Console()


class JingleProvider:
    """Jingle audio provider
    
    Scans assets/jingles/ directory and provides random selection
    of jingle files for segment boundary insertion.
    """
    
    def __init__(self, jingles_dir: Path = Path("assets/jingles")):
        """Initialize jingle provider
        
        Args:
            jingles_dir: Directory containing jingle audio files
        """
        self.jingles_dir = jingles_dir
        self._jingles_cache: list[Path] = []
        self._load_jingles()
    
    def _load_jingles(self):
        """Scan jingles directory and cache available files"""
        if not self.jingles_dir.exists():
            logger.warning(f"Jingles directory not found: {self.jingles_dir}")
            console.print(f"[yellow]⚠ Jingles directory not found: {self.jingles_dir}[/yellow]")
            console.print(f"[yellow]  Jingle insertion will be disabled[/yellow]")
            return
        
        # Scan for audio files (.mp3, .wav, .ogg, .m4a)
        audio_extensions = ["*.mp3", "*.wav", "*.ogg", "*.m4a"]
        for ext in audio_extensions:
            self._jingles_cache.extend(self.jingles_dir.glob(ext))
        
        if self._jingles_cache:
            console.print(f"[dim]Loaded {len(self._jingles_cache)} jingles from {self.jingles_dir}[/dim]")
            logger.info(f"Loaded {len(self._jingles_cache)} jingles: {[j.name for j in self._jingles_cache]}")
        else:
            logger.warning(f"No jingle files found in {self.jingles_dir}")
            console.print(f"[yellow]⚠ No jingle files found in {self.jingles_dir}[/yellow]")
    
    def get_random_jingle(self) -> Optional[Path]:
        """Get a random jingle file
        
        Returns:
            Path: Random jingle file path, or None if no jingles available
        """
        if not self._jingles_cache:
            return None
        
        import random
        selected = random.choice(self._jingles_cache)
        logger.debug(f"Selected jingle: {selected.name}")
        return selected
    
    def get_jingle_duration(self, jingle_path: Path) -> float:
        """Get jingle audio duration in seconds
        
        Args:
            jingle_path: Path to jingle audio file
        
        Returns:
            float: Duration in seconds
        """
        try:
            audio = AudioSegment.from_file(str(jingle_path))
            duration_sec = len(audio) / 1000.0
            logger.debug(f"Jingle {jingle_path.name} duration: {duration_sec:.2f}s")
            return duration_sec
        except Exception as e:
            logger.error(f"Failed to get jingle duration for {jingle_path}: {e}")
            # Return default duration as fallback
            return 3.0
    
    def is_available(self) -> bool:
        """Check if jingles are available
        
        Returns:
            bool: True if at least one jingle is available
        """
        return len(self._jingles_cache) > 0
