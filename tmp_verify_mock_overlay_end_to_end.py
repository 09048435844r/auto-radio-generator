import asyncio
import json
from pathlib import Path

from core.models import Script, load_config
from services.audio_synthesis.voicevox_client import VoicevoxClient
from services.video_rendering.ffmpeg_renderer import FfmpegRenderer


async def main() -> None:
    project_root = Path('.')
    cfg = load_config(project_root)
    cfg.yaml.dev.mock_mode = True

    script_data = json.loads((project_root / 'tests/mock_data/script.json').read_text(encoding='utf-8'))
    script = Script.model_validate(script_data)

    output_dir = project_root / 'output' / 'tmp_mock_verify'
    output_dir.mkdir(parents=True, exist_ok=True)

    voicevox = VoicevoxClient(cfg)
    synthesis = await voicevox.synthesize(script=script, output_dir=output_dir)

    renderer = FfmpegRenderer(cfg)
    cmd = renderer._build_ffmpeg_command(
        background_image=project_root / cfg.yaml.paths.background_image,
        audio_file=synthesis.audio_path,
        bgm_file=project_root / cfg.yaml.paths.bgm_file,
        subtitle_file=synthesis.subtitle_path,
        output_path=output_dir / 'mock_overlay_check.mp4',
        resolution=cfg.yaml.video_renderer.output_resolution,
        fps=cfg.yaml.video_renderer.output_fps,
        bgm_volume=cfg.yaml.video_renderer.bgm_volume,
        fade_in_sec=cfg.yaml.video_renderer.bgm_fade_in_sec,
        fade_out_sec=cfg.yaml.video_renderer.bgm_fade_out_sec,
        total_duration_sec=synthesis.total_duration_sec,
        chapters=synthesis.chapters,
    )

    filter_complex = cmd[cmd.index('-filter_complex') + 1]

    print('MOCK_CHAPTER_COUNT', len(synthesis.chapters))
    print('HAS_TOPIC_OVERLAY', '話題：' in filter_complex)
    print('BETWEEN_COUNT', filter_complex.count("between(t,"))
    print('HAS_FONTFILE', "fontfile='C\\:/Windows/Fonts" in filter_complex)
    print('FILTER_COMPLEX_START')
    print(filter_complex)
    print('FILTER_COMPLEX_END')


if __name__ == '__main__':
    asyncio.run(main())
