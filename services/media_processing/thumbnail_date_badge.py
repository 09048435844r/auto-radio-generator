"""日付バッジ描画メソッド"""

def add_date_badge_method():
    """ThumbnailGeneratorクラスに追加する日付バッジ描画メソッド"""
    
    method_code = '''
    def _draw_date_badge(self, img: Image.Image) -> Image.Image:
        """右上に日付バッジを描画
        
        Args:
            img: ベース画像
        
        Returns:
            Image.Image: バッジ描画後の画像
        """
        draw = ImageDraw.Draw(img)
        
        # 現在の日付を取得
        current_date = datetime.now().strftime("%Y.%m.%d制作")
        
        # フォント設定
        font_size = 45
        font = None
        for font_path in self.font_paths:
            try:
                font = ImageFont.truetype(str(font_path), font_size)
                break
            except Exception:
                continue
        
        if not font:
            font = ImageFont.load_default()
        
        # テキストサイズを計測
        bbox = draw.textbbox((0, 0), current_date, font=font)
        text_width = bbox[2] - bbox[0]
        text_height = bbox[3] - bbox[1]
        
        # バッジの位置とサイズ
        margin = 50
        padding_x = 20
        padding_y = 15
        badge_width = text_width + padding_x * 2
        badge_height = text_height + padding_y * 2
        
        # 右上に配置
        badge_x = self.THUMBNAIL_WIDTH - badge_width - margin
        badge_y = margin
        
        # 角丸長方形の背景を描画
        badge_rect = [
            badge_x,
            badge_y,
            badge_x + badge_width,
            badge_y + badge_height
        ]
        
        # 背景色（赤）
        draw.rounded_rectangle(
            badge_rect,
            radius=10,
            fill="#CC0000",
            outline=None
        )
        
        # テキストを中央に配置
        text_x = badge_x + padding_x
        text_y = badge_y + padding_y
        
        # 白文字で描画
        draw.text(
            (text_x, text_y),
            current_date,
            font=font,
            fill="#FFFFFF"
        )
        
        return img
    '''
    
    return method_code
