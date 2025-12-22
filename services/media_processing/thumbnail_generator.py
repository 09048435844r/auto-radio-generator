"""YouTubeサムネイル画像生成サービス"""
from pathlib import Path
from typing import Optional

from PIL import Image, ImageDraw, ImageFont, ImageFilter, ImageEnhance
from rich.console import Console

console = Console()


class ThumbnailGenerator:
    """YouTube投稿用サムネイル画像を自動生成
    
    背景画像にタイトルテキストを重ねて、視認性の高いサムネイルを作成します。
    """
    
    # YouTube推奨サイズ
    THUMBNAIL_WIDTH = 1280
    THUMBNAIL_HEIGHT = 720
    
    def __init__(self):
        """サムネイル生成器を初期化"""
        self.font_paths = self._find_japanese_fonts()
    
    def _find_japanese_fonts(self) -> list[Path]:
        """日本語フォントのパスを探索
        
        Returns:
            list[Path]: 利用可能なフォントパスのリスト（優先順）
        """
        candidates = [
            # Windows標準フォント
            Path("C:/Windows/Fonts/meiryo.ttc"),
            Path("C:/Windows/Fonts/msgothic.ttc"),
            Path("C:/Windows/Fonts/msmincho.ttc"),
            Path("C:/Windows/Fonts/YuGothB.ttc"),
            # FFmpegで使用しているフォント
            Path("C:/Windows/Fonts/arial.ttf"),
        ]
        
        available = [p for p in candidates if p.exists()]
        
        if not available:
            console.print("[yellow]⚠ 日本語フォントが見つかりません。デフォルトフォントを使用します。[/yellow]")
        
        return available
    
    def generate(
        self,
        title: str,
        background_path: Path,
        output_path: Path,
        darken_factor: float = 0.5,
        blur_radius: int = 3
    ) -> Path:
        """サムネイル画像を生成
        
        Args:
            title: 動画タイトル
            background_path: 背景画像のパス
            output_path: 出力先パス
            darken_factor: 背景を暗くする係数 (0.0-1.0, 小さいほど暗い)
            blur_radius: ブラー半径 (0で無効)
        
        Returns:
            Path: 生成されたサムネイル画像のパス
        """
        console.print(f"[cyan]サムネイル画像を生成中...[/cyan]")
        console.print(f"  タイトル: {title}")
        console.print(f"  背景: {background_path.name}")
        
        # 1. 背景画像を読み込み、リサイズ
        background = self._load_and_resize_background(background_path)
        
        # 2. 背景を暗くしてブラーをかける（視認性向上）
        background = self._apply_effects(background, darken_factor, blur_radius)
        
        # 3. タイトルテキストを描画
        thumbnail = self._draw_title_text(background, title)
        
        # 4. 保存
        output_path.parent.mkdir(parents=True, exist_ok=True)
        thumbnail.save(output_path, "PNG", quality=95)
        
        file_size_kb = output_path.stat().st_size / 1024
        console.print(f"[green]✓ サムネイル生成完了[/green] {output_path.name} ({file_size_kb:.1f} KB)")
        
        return output_path
    
    def _load_and_resize_background(self, background_path: Path) -> Image.Image:
        """背景画像を読み込み、サムネイルサイズにリサイズ
        
        Args:
            background_path: 背景画像のパス
        
        Returns:
            Image.Image: リサイズされた背景画像
        """
        img = Image.open(background_path)
        
        # アスペクト比を維持しながらリサイズ（中央クロップ）
        img_ratio = img.width / img.height
        target_ratio = self.THUMBNAIL_WIDTH / self.THUMBNAIL_HEIGHT
        
        if img_ratio > target_ratio:
            # 画像が横長 → 高さを合わせて横をクロップ
            new_height = self.THUMBNAIL_HEIGHT
            new_width = int(new_height * img_ratio)
        else:
            # 画像が縦長 → 幅を合わせて縦をクロップ
            new_width = self.THUMBNAIL_WIDTH
            new_height = int(new_width / img_ratio)
        
        img = img.resize((new_width, new_height), Image.Resampling.LANCZOS)
        
        # 中央クロップ
        left = (new_width - self.THUMBNAIL_WIDTH) // 2
        top = (new_height - self.THUMBNAIL_HEIGHT) // 2
        right = left + self.THUMBNAIL_WIDTH
        bottom = top + self.THUMBNAIL_HEIGHT
        
        img = img.crop((left, top, right, bottom))
        
        return img
    
    def _apply_effects(
        self,
        img: Image.Image,
        darken_factor: float,
        blur_radius: int
    ) -> Image.Image:
        """背景画像にエフェクトを適用（暗くする + ブラー）
        
        Args:
            img: 元画像
            darken_factor: 暗くする係数 (0.0-1.0)
            blur_radius: ブラー半径
        
        Returns:
            Image.Image: エフェクト適用後の画像
        """
        # 暗くする
        enhancer = ImageEnhance.Brightness(img)
        img = enhancer.enhance(darken_factor)
        
        # ブラーをかける
        if blur_radius > 0:
            img = img.filter(ImageFilter.GaussianBlur(radius=blur_radius))
        
        return img
    
    def _draw_title_text(self, img: Image.Image, title: str) -> Image.Image:
        """タイトルテキストを画像に描画（動的サイズ調整）
        
        Args:
            img: ベース画像
            title: タイトルテキスト
        
        Returns:
            Image.Image: テキスト描画後の画像
        """
        draw = ImageDraw.Draw(img)
        
        # 安全マージン：画像幅の90%を最大幅とする
        max_text_width = int(self.THUMBNAIL_WIDTH * 0.9)
        
        # PM提供の_get_fitted_fontを使用して最適なフォントを取得
        # フォントパスは最初に見つかったものを使用
        font_path = self.font_paths[0] if self.font_paths else None
        if font_path:
            font = self._get_fitted_font(draw, title, font_path, max_text_width, max_size=120, min_size=40)
        else:
            # フォントパスがない場合はデフォルトフォント
            font = ImageFont.load_default()
        
        # タイトルを適切に改行
        lines = self._wrap_text(title, font, max_width=max_text_width)
        
        # テキストの全体サイズを計算
        line_heights = []
        for line in lines:
            bbox = draw.textbbox((0, 0), line, font=font)
            line_heights.append(bbox[3] - bbox[1])
        
        total_height = sum(line_heights) + (len(lines) - 1) * 20  # 行間20px
        
        # 中央配置の開始Y座標
        y = (self.THUMBNAIL_HEIGHT - total_height) // 2
        
        # 各行を描画
        for line, line_height in zip(lines, line_heights):
            # テキストの幅を計算して中央揃え
            bbox = draw.textbbox((0, 0), line, font=font)
            text_width = bbox[2] - bbox[0]
            x = (self.THUMBNAIL_WIDTH - text_width) // 2
            
            # 黒フチ（ストローク）を描画
            self._draw_text_with_outline(
                draw, (x, y), line, font,
                fill_color="white",
                outline_color="black",
                outline_width=6
            )
            
            y += line_height + 20  # 次の行へ
        
        return img
    
    def _calculate_optimal_font_size(
        self,
        text: str,
        max_width: int,
        draw: ImageDraw.ImageDraw,
        max_font_size: int = 100,
        min_font_size: int = 40
    ) -> int:
        """テキストが指定幅に収まる最適なフォントサイズを計算
        
        Args:
            text: 計測するテキスト
            max_width: 最大幅（ピクセル）
            draw: ImageDrawオブジェクト
            max_font_size: 最大フォントサイズ
            min_font_size: 最小フォントサイズ
        
        Returns:
            int: 最適なフォントサイズ
        """
        current_size = max_font_size
        
        while current_size >= min_font_size:
            font = self._load_font(size=current_size)
            text_width = self._measure_text_width(text, font, draw)
            
            # 最大幅に収まればOK
            if text_width <= max_width:
                return current_size
            
            # サイズを減らして再チェック
            current_size -= 5
        
        # 最小サイズに達した
        return min_font_size
    
    def _measure_text_width(
        self,
        text: str,
        font: ImageFont.FreeTypeFont,
        draw: ImageDraw.ImageDraw
    ) -> int:
        """テキストの描画幅を計測
        
        Args:
            text: 計測するテキスト
            font: フォント
            draw: ImageDrawオブジェクト
        
        Returns:
            int: テキスト幅（ピクセル）
        """
        bbox = draw.textbbox((0, 0), text, font=font)
        return bbox[2] - bbox[0]
    
    def _get_fitted_font(self, draw, text, font_path, max_width, max_size=120, min_size=40):
        """指定された幅(max_width)に収まる最大のフォントサイズを計算して返す"""
        current_size = max_size
        
        while current_size >= min_size:
            try:
                font = ImageFont.truetype(str(font_path), current_size)
            except OSError:
                font = ImageFont.load_default()
                break
            
            # テキストの描画サイズを取得 (left, top, right, bottom)
            bbox = draw.textbbox((0, 0), text, font=font)
            text_width = bbox[2] - bbox[0]
            
            if text_width <= max_width:
                return font
            
            # 幅に収まらない場合はサイズを下げて再試行
            current_size -= 5
            
        # 最小サイズでも入らない場合は最小サイズを返す
        return ImageFont.truetype(str(font_path), min_size)
    
    def _load_font(self, size: int) -> ImageFont.FreeTypeFont:
        """フォントを読み込み
        
        Args:
            size: フォントサイズ
        
        Returns:
            ImageFont.FreeTypeFont: フォントオブジェクト
        """
        for font_path in self.font_paths:
            try:
                return ImageFont.truetype(str(font_path), size)
            except Exception:
                continue
        
        # フォールバック: デフォルトフォント
        console.print("[yellow]⚠ カスタムフォントの読み込みに失敗。デフォルトフォントを使用します。[/yellow]")
        return ImageFont.load_default()
    
    def _wrap_text(
        self,
        text: str,
        font: ImageFont.FreeTypeFont,
        max_width: int
    ) -> list[str]:
        """テキストを指定幅で改行
        
        Args:
            text: 元のテキスト
            font: フォント
            max_width: 最大幅（ピクセル）
        
        Returns:
            list[str]: 改行されたテキスト行のリスト
        """
        lines = []
        words = text.split()
        
        if not words:
            return [text]
        
        current_line = words[0]
        
        for word in words[1:]:
            # 仮の行を作成
            test_line = current_line + " " + word
            
            # 幅を計算
            bbox = ImageDraw.Draw(Image.new('RGB', (1, 1))).textbbox(
                (0, 0), test_line, font=font
            )
            width = bbox[2] - bbox[0]
            
            if width <= max_width:
                current_line = test_line
            else:
                lines.append(current_line)
                current_line = word
        
        lines.append(current_line)
        
        # 最大3行に制限
        if len(lines) > 3:
            lines = lines[:3]
            lines[-1] += "..."
        
        return lines
    
    def _draw_text_with_outline(
        self,
        draw: ImageDraw.ImageDraw,
        position: tuple[int, int],
        text: str,
        font: ImageFont.FreeTypeFont,
        fill_color: str = "white",
        outline_color: str = "black",
        outline_width: int = 3
    ) -> None:
        """アウトライン付きテキストを描画
        
        Args:
            draw: ImageDrawオブジェクト
            position: 描画位置 (x, y)
            text: テキスト
            font: フォント
            fill_color: 塗りつぶし色
            outline_color: アウトライン色
            outline_width: アウトライン幅
        """
        x, y = position
        
        # アウトラインを描画（8方向 + 斜め）
        for dx in range(-outline_width, outline_width + 1):
            for dy in range(-outline_width, outline_width + 1):
                if dx != 0 or dy != 0:
                    draw.text((x + dx, y + dy), text, font=font, fill=outline_color)
        
        # メインテキストを描画
        draw.text((x, y), text, font=font, fill=fill_color)
