from pathlib import Path

from core.interfaces import ChapterMarker
from core.models import load_config
from services.video_rendering.ffmpeg_renderer import FfmpegRenderer

cfg = load_config(Path('.'))
renderer = FfmpegRenderer(cfg)
quote = chr(39)

chapters = [
    ChapterMarker(start_time_sec=2.0, title=f"Intro: owner{quote}s note, part1", section_id="intro"),
    ChapterMarker(
        start_time_sec=38.5,
        title="This is a very long chapter title that should be truncated for overlay",
        section_id="main",
    ),
    ChapterMarker(start_time_sec=77.25, title="Summary", section_id="ending"),
]

cmd = renderer._build_ffmpeg_command(
    background_image=Path("assets/backgrounds/default.png"),
    audio_file=Path("tests/mock_data/audio/combined_audio.wav"),
    bgm_file=Path("assets/bgm/default.mp3"),
    subtitle_file=Path("tests/mock_data/audio/subtitles.ass"),
    output_path=Path("output/tmp.mp4"),
    resolution="1920x1080",
    fps=30,
    bgm_volume=0.15,
    fade_in_sec=3.0,
    fade_out_sec=3.0,
    total_duration_sec=120.0,
    chapters=chapters,
)

filter_complex = cmd[cmd.index("-filter_complex") + 1]

print("BETWEEN_COUNT", filter_complex.count("between(t,"))
print("HAS_BOXBORDER", "boxborderw=10" in filter_complex)
print("HAS_ESCAPED_COLON", "\\:" in filter_complex)
print("HAS_ESCAPED_COMMA", "\\," in filter_complex)
print("HAS_ESCAPED_QUOTE", "\\'" in filter_complex)
print("HAS_TRUNCATED", "..." in filter_complex)
print("FILTER_COMPLEX_START")
print(filter_complex)
print("FILTER_COMPLEX_END")
