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

    output_dir = project_root / 'output' / 'tmp_subtitle_chain_verify'
    output_dir.mkdir(parents=True, exist_ok=True)

    synthesis = await VoicevoxClient(cfg).synthesize(script=script, output_dir=output_dir)
    print('SUBTITLE_PATH', synthesis.subtitle_path)
    print('SUBTITLE_EXISTS', synthesis.subtitle_path.exists())

    renderer = FfmpegRenderer(cfg)

    for show_overlay in (True, False):
        cfg.yaml.video.show_topic_overlay = show_overlay
        cmd = renderer._build_ffmpeg_command(
            background_image=project_root / cfg.yaml.paths.background_image,
            audio_file=synthesis.audio_path,
            bgm_file=project_root / cfg.yaml.paths.bgm_file,
            subtitle_file=synthesis.subtitle_path,
            output_path=output_dir / f'check_{show_overlay}.mp4',
            resolution=cfg.yaml.video_renderer.output_resolution,
            fps=cfg.yaml.video_renderer.output_fps,
            bgm_volume=cfg.yaml.video_renderer.bgm_volume,
            fade_in_sec=cfg.yaml.video_renderer.bgm_fade_in_sec,
            fade_out_sec=cfg.yaml.video_renderer.bgm_fade_out_sec,
            total_duration_sec=synthesis.total_duration_sec,
            chapters=synthesis.chapters,
        )
        filter_complex = cmd[cmd.index('-filter_complex') + 1]
        print('SHOW_OVERLAY', show_overlay)
        print('HAS_SUBTITLES_ASS', "subtitles='" in filter_complex and '.ass' in filter_complex)
        print('HAS_TOPIC', '話題：' in filter_complex)
        print('FILTER_COMPLEX_START')
        print(filter_complex)
        print('FILTER_COMPLEX_END')


if __name__ == '__main__':
    asyncio.run(main())
