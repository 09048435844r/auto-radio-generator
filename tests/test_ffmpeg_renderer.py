"""FfmpegRenderer のユニットテスト

FFmpegを実際に実行せず、パス変換ロジックの正当性だけを検証する。
"""
import pytest

from services.video_rendering.ffmpeg_renderer import FfmpegRenderer


class TestEscapeWindowsPath:
    """_escape_windows_path メソッドのテスト"""

    @pytest.fixture
    def renderer(self, mock_app_config):
        """テスト用 FfmpegRenderer インスタンス（FFmpeg実行なし）"""
        return FfmpegRenderer(mock_app_config)

    # ------------------------------------------------------------------
    # 基本的な Windows パス変換
    # ------------------------------------------------------------------
    def test_basic_windows_absolute_path(self, renderer):
        """標準的な Windows 絶対パスが正しく変換される"""
        result = renderer._escape_windows_path(r"E:\windsurf\auto_radio_generator\output\subtitles.ass")
        assert result == "E\\:/windsurf/auto_radio_generator/output/subtitles.ass"

    def test_drive_letter_colon_escaped(self, renderer):
        """ドライブレターのコロンが \\: にエスケープされる"""
        result = renderer._escape_windows_path(r"C:\Windows\Fonts\arial.ttf")
        assert result == "C\\:/Windows/Fonts/arial.ttf"

    def test_backslashes_replaced_with_forward_slashes(self, renderer):
        """すべてのバックスラッシュがスラッシュに置換される"""
        result = renderer._escape_windows_path(r"D:\a\b\c\d.txt")
        assert "\\" not in result.replace("\\:", "")  # \: 以外のバックスラッシュがない

    # ------------------------------------------------------------------
    # エッジケース
    # ------------------------------------------------------------------
    def test_path_with_spaces(self, renderer):
        """スペースを含むパスが正しく変換される"""
        result = renderer._escape_windows_path(r"C:\Users\My User\Documents\file.ass")
        assert result == "C\\:/Users/My User/Documents/file.ass"

    def test_path_with_japanese_characters(self, renderer):
        """日本語文字を含むパスが正しく変換される"""
        result = renderer._escape_windows_path(r"E:\プロジェクト\出力\字幕.ass")
        assert result == "E\\:/プロジェクト/出力/字幕.ass"

    def test_unix_style_path_unchanged(self, renderer):
        """Unix形式のパスはバックスラッシュがないのでコロンのみエスケープ"""
        result = renderer._escape_windows_path("/home/user/file.ass")
        assert result == "/home/user/file.ass"

    def test_empty_string(self, renderer):
        """空文字列を渡しても例外が発生しない"""
        result = renderer._escape_windows_path("")
        assert result == ""

    def test_multiple_colons(self, renderer):
        """複数のコロンがすべてエスケープされる（ドライブレター + ポート等）"""
        result = renderer._escape_windows_path(r"C:\path\to\file:zone.ass")
        assert result == "C\\:/path/to/file\\:zone.ass"

    def test_already_forward_slashes(self, renderer):
        """既にスラッシュのパスはスラッシュのまま維持される"""
        result = renderer._escape_windows_path("C:/Users/test/file.ass")
        assert result == "C\\:/Users/test/file.ass"

    def test_unc_path(self, renderer):
        r"""UNCパス (\\server\share) が正しく変換される"""
        result = renderer._escape_windows_path(r"\\server\share\folder\file.ass")
        assert result == "//server/share/folder/file.ass"
