"""
サムネイル再作成機能とState管理の回帰テスト

Gradio 4.0へのアップデートに備え、
- generate_video_mock のState生成
- ThumbnailGenerator.regenerate_with_new_title のロジック
を保護するためのテスト。
"""

import pytest
from unittest.mock import Mock, patch, MagicMock
from dataclasses import dataclass
from typing import Tuple, Optional

# Auto Radio Generator imports
from workflow import ThumbnailRegenerationState
from app import generate_video_mock


class TestThumbnailRegenerationState:
    """ThumbnailRegenerationState の基本テスト"""

    def test_state_creation(self):
        """Stateが正しく作成されることを確認"""
        state = ThumbnailRegenerationState(
            theme="テストテーマ",
            script_summary="テスト要約",
            output_dir="test/output",
            background_path="test/bg.png",
            base_title="元タイトル",
            generation_count=1
        )
        
        assert state.theme == "テストテーマ"
        assert state.script_summary == "テスト要約"
        assert state.output_dir == "test/output"
        assert state.background_path == "test/bg.png"
        assert state.base_title == "元タイトル"
        assert state.generation_count == 1


class TestGenerateVideoMock:
    """generate_video_mock のテスト"""

    @patch('app.generate_video')
    def test_generate_video_mock_returns_state(self, mock_generate_video):
        """generate_video_mock が generate_video を呼び出し、Stateを含む7要素を返すことを確認"""
        # モックの戻り値を設定
        mock_state = ThumbnailRegenerationState(
            theme="モックテーマ",
            script_summary="モック要約",
            output_dir="mock/output",
            background_path="mock/bg.png",
            base_title="モック元タイトル",
            generation_count=0
        )
        
        mock_generate_video.return_value = (
            "mock_video.mp4",      # video_path
            "テストログ",           # log_text
            "テストコスト",         # cost_text
            "テストタイトル",       # title
            "テスト説明",           # description
            "https://youtube.com/watch?v=test",  # youtube_url
            mock_state              # thumbnail_state
        )
        
        # generate_video_mock を実行
        mock_progress = Mock()
        result = generate_video_mock(
            theme="テストテーマ",
            research_mode="trivia",
            background_image="test_bg.png",
            bgm_file="test_bgm.mp3",
            bgm_volume=0.5,
            fade_time=1.0,
            speed_scale=1.0,
            enable_spectrum=False,
            avoid_topics="テスト,サンプル",
            upload_to_youtube=False,
            footer_text="フッター",
            second_mode="なし",
            jingle_choice="なし",
            jingle_custom_path="",
            progress=mock_progress
        )
        
        # 戻り値の検証
        assert isinstance(result, tuple)
        assert len(result) == 7, f"Expected 7 elements, got {len(result)}"
        
        video_path, log_text, cost_text, title, description, youtube_url, thumbnail_state = result
        
        assert video_path == "mock_video.mp4"
        assert log_text == "テストログ"
        assert cost_text == "テストコスト"
        assert title == "テストタイトル"
        assert description == "テスト説明"
        assert youtube_url == "https://youtube.com/watch?v=test"
        assert isinstance(thumbnail_state, ThumbnailRegenerationState)
        
        # Stateの内容検証
        assert thumbnail_state.theme == "モックテーマ"
        assert thumbnail_state.script_summary == "モック要約"
        assert thumbnail_state.output_dir == "mock/output"
        assert thumbnail_state.background_path == "mock/bg.png"
        assert thumbnail_state.base_title == "モック元タイトル"
        assert thumbnail_state.generation_count == 0
        
        # generate_video が正しい引数で呼ばれたことを確認
        mock_generate_video.assert_called_once_with(
            theme="テストテーマ",
            research_mode="trivia",
            background_image="test_bg.png",
            bgm_file="test_bgm.mp3",
            bgm_volume=0.5,
            fade_time=1.0,
            speed_scale=1.0,
            enable_spectrum=False,
            use_mock=True,
            avoid_topics="テスト,サンプル",
            upload_to_youtube=False,
            footer_text="フッター",
            second_mode="なし",
            jingle_choice="なし",
            jingle_custom_path="",
            progress=mock_progress
        )


class TestThumbnailRegeneration:
    """ThumbnailGenerator.regenerate_with_new_title のテスト"""

    @patch('services.script_generation.gemini_client.GeminiClient')
    @patch('core.models.config.load_config')
    @patch('core.prompt_manager.PromptManager')
    @patch('services.media_processing.thumbnail_generator.ThumbnailGenerator._apply_effects')
    @patch('services.media_processing.thumbnail_generator.ThumbnailGenerator._draw_title_text')
    @patch('services.media_processing.thumbnail_generator.ThumbnailGenerator._draw_date_badge')
    @patch('pathlib.Path.stat')
    @patch('services.media_processing.thumbnail_generator.Image')
    @patch('os.path')
    @patch('os.makedirs')
    @patch('services.media_processing.thumbnail_generator.console')
    def test_regenerate_with_new_title_success(
        self, 
        mock_console, 
        mock_os, 
        mock_makedirs,
        mock_image,
        mock_stat,
        mock_draw_date_badge,
        mock_draw_title_text,
        mock_apply_effects,
        mock_prompt_manager_class,
        mock_load_config,
        mock_gemini_client_class
    ):
        """サムネイル再作成が成功することを確認"""
        from services.media_processing.thumbnail_generator import ThumbnailGenerator
        
        # モックの設定
        mock_config = Mock()
        mock_config.yaml.script_generator.gemini.flash_model = "gemini-2.5-flash"
        mock_load_config.return_value = mock_config
        
        mock_prompt_manager = Mock()
        mock_prompt = "テーマ: {theme}\n要約: {script_summary}"
        mock_prompt_manager.get_prompt.return_value = mock_prompt
        mock_prompt_manager_class.return_value = mock_prompt_manager
        
        mock_gemini_client = Mock()
        # ダミーのJSONレスポンス
        dummy_response = '''{"thumbnail_title": "新サムネイル", "video_title": "新動画タイトル"}'''
        mock_gemini_client._call_api.return_value = (dummy_response, {"usage": 10})
        mock_gemini_client_class.return_value = mock_gemini_client
        
        # Image モック
        mock_img = Mock()
        mock_img.width = 1920
        mock_img.height = 1080
        mock_img.size = (1920, 1080)
        mock_img.mode = "RGB"
        mock_img.resize.return_value = mock_img
        mock_img.crop.return_value = mock_img
        mock_img.getbands.return_value = ["R", "G", "B"]
        mock_image.new.return_value = mock_img
        mock_image.open.return_value = mock_img
        
        # _apply_effects モック
        mock_apply_effects.return_value = mock_img
        
        # _draw_title_text モック
        mock_draw_title_text.return_value = mock_img
        
        # _draw_date_badge モック
        mock_draw_date_badge.return_value = mock_img
        
        # Path.stat モック
        mock_stat_result = Mock()
        mock_stat_result.st_size = 1024  # 1KB
        mock_stat_result.st_mode = 16877  # ディレクトリのモード (0o40755)
        mock_stat.return_value = mock_stat_result
        
        # os モック
        mock_os.path.join.return_value = "test/output/new_thumbnail.png"
        mock_os.path.exists.return_value = False
        mock_makedirs.return_value = None
        
        # ThumbnailGenerator をテスト
        generator = ThumbnailGenerator()
        
        result = generator.regenerate_with_new_title(
            theme="テストテーマ",
            script_summary="テスト要約",
            output_dir="test/output",
            background_path="test/bg.png",
            base_title="元タイトル",
            generation_count=1
        )
        
        # 戻り値の検証
        assert isinstance(result, tuple)
        assert len(result) == 3
        
        thumbnail_path, video_title, thumbnail_title = result
        
        assert thumbnail_path.endswith(".png")
        assert video_title == "元タイトル"  # base_titleがそのまま返される
        assert thumbnail_title == "新サムネイル"
        
        # API呼び出しの検証
        mock_gemini_client._call_api.assert_called_once()
        call_args = mock_gemini_client._call_api.call_args
        
        # _call_api の引数を検証
        assert call_args.kwargs['model_override'] == "gemini-2.5-flash"
        assert call_args.kwargs['use_schema'] is False
        assert call_args.kwargs['phase'] == "thumbnail_regeneration"
        
        # プロンプトのフォーマット検証
        # call_args.args は空なので、kwargs から取得
        formatted_prompt = call_args.kwargs['user_prompt']
        assert "テーマ: テストテーマ" in formatted_prompt
        assert "要約: テスト要約" in formatted_prompt
        
        # 画像保存の検証
        mock_img.save.assert_called_once()
        # 呼び出された引数を確認
        save_call = mock_img.save.call_args
        assert str(save_call.args[0]).endswith(".png")  # ファイルパス
        assert save_call.args[1] == 'PNG'  # フォーマット
        assert save_call.kwargs['quality'] == 95  # 品質

    @patch('services.script_generation.gemini_client.GeminiClient')
    @patch('core.models.config.load_config')
    @patch('core.prompt_manager.PromptManager')
    def test_regenerate_with_new_title_api_error(
        self, 
        mock_prompt_manager_class,
        mock_load_config,
        mock_gemini_client_class
    ):
        """APIエラー時に例外が発生することを確認"""
        from services.media_processing.thumbnail_generator import ThumbnailGenerator
        
        # モックの設定
        mock_config = Mock()
        mock_config.yaml.script_generator.gemini.flash_model = "gemini-2.5-flash"
        mock_load_config.return_value = mock_config
        
        mock_prompt_manager = Mock()
        mock_prompt_manager.get_prompt.return_value = "dummy prompt"
        mock_prompt_manager_class.return_value = mock_prompt_manager
        
        mock_gemini_client = Mock()
        mock_gemini_client._call_api.side_effect = Exception("API Error")
        mock_gemini_client_class.return_value = mock_gemini_client
        
        generator = ThumbnailGenerator()
        
        # 例外が発生することを確認
        with pytest.raises(Exception, match="API Error"):
            generator.regenerate_with_new_title(
                theme="テストテーマ",
                script_summary="テスト要約",
                output_dir="test/output",
                background_path="test/bg.png",
                base_title="元タイトル",
                generation_count=0
            )


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
