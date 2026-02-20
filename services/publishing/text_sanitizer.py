"""YouTube概要欄用テキストサニタイズユーティリティ"""
import re
import unicodedata
from typing import Optional
from urllib.parse import urlparse

# YouTubeで問題になりやすい文字の制御
CONTROL_CHARS = re.compile(r'[\x00-\x1F\x7F-\x9F]')

# YouTubeチャプター認識を妨げる可能性のある文字
CHAPTER_PROBLEMATIC = re.compile(r'[^\w\s\-:().\u3040-\u309F\u30A0-\u30FF\u4E00-\u9FFF]')

# 許可する絵文字（YouTubeで安全に表示されるもの）
ALLOWED_EMOJIS = {'📄', '🔗', '🎵', '🎬', '📝', '🎯', '🎪', '🎭'}

# URL検証用正規表現（http/httpsのみ許可）
URL_PATTERN = re.compile(
    r'^https?://'  # http:// or https://のみ
    r'(?:(?:[A-Z0-9](?:[A-Z0-9-]{0,61}[A-Z0-9])?\.)+[A-Z]{2,6}\.?|'  # domain...
    r'localhost|'  # localhost...
    r'\d{1,3}\.\d{1,3}\.\d{1,3}\.\d{1,3})'  # ...or ip
    r'(?::\d+)?'  # optional port
    r'(?:/?|[/?]\S+)$', re.IGNORECASE)


def sanitize_for_youtube(text: str, max_length: int = 5000) -> str:
    """YouTube用にテキストをサニタイズ
    
    Args:
        text: サニタイズ対象のテキスト
        max_length: 最大文字数（デフォルト: 5000）
        
    Returns:
        サニタイズされたテキスト
    """
    if not text:
        return ""
    
    # Unicode正規化（NFC形式）
    text = unicodedata.normalize('NFC', text)
    
    # 制御文字を削除
    text = CONTROL_CHARS.sub('', text)
    
    # 長さ制限
    if len(text) > max_length:
        # 参考文献セクションを優先的に切り詰め
        lines = text.split('\n')
        ref_section_start = -1
        
        for i, line in enumerate(lines):
            if '【参考文献】' in line:
                ref_section_start = i
                break
        
        if ref_section_start >= 0:
            # 参考文献セクションを短くする
            before_refs = lines[:ref_section_start]
            ref_lines = lines[ref_section_start:]
            
            # 参考文献を1件ずつ削除して長さを調整
            while len('\n'.join(before_refs + ref_lines)) > max_length and len(ref_lines) > 3:
                # 参考文献アイテムを削除（3行: タイトル、URL、空行）
                if len(ref_lines) >= 4:
                    ref_lines = ref_lines[:-4]  # 最後の参考文献を削除
                else:
                    break
            
            text = '\n'.join(before_refs + ref_lines)
        
        # それでも長い場合は末尾を切り詰め
        if len(text) > max_length:
            text = text[:max_length-3] + '...'
    
    return text


def sanitize_title(title: str) -> str:
    """WebページタイトルをYouTube表示用にサニタイズ
    
    Args:
        title: スクレイピングしたタイトル
        
    Returns:
        サニタイズされたタイトル
    """
    if not title:
        return ""
    
    # Unicode正規化
    title = unicodedata.normalize('NFC', title)
    
    # 制御文字を削除
    title = CONTROL_CHARS.sub('', title)
    
    # 連続する空白を単一化
    title = re.sub(r'\s+', ' ', title)
    
    # 前後の空白を削除
    title = title.strip()
    
    # 長すぎる場合は省略
    if len(title) > 100:
        title = title[:97] + '...'
    
    return title


def validate_url(url: str) -> bool:
    """URLが有効な形式か検証
    
    Args:
        url: 検証するURL文字列
        
    Returns:
        有効な場合はTrue
    """
    if not url:
        return False
    
    try:
        result = urlparse(url)
        # http/httpsのみ許可
        if result.scheme not in ('http', 'https'):
            return False
        return all([result.scheme, result.netloc])
    except Exception:
        return False


def normalize_url(url: str) -> str:
    """URLを正規化（https統一、末尾スラッシュ削除）
    
    Args:
        url: 正規化するURL
        
    Returns:
        正規化されたURL
    """
    if not url:
        return url
    
    # httpをhttpsに統一
    if url.startswith('http://'):
        url = 'https://' + url[7:]
    
    # 末尾のスラッシュを削除
    if url.endswith('/') and url != 'https://':
        url = url[:-1]
    
    return url


def validate_chapter_format(chapter_lines: list[str]) -> bool:
    """チャプター形式がYouTube認識可能か検証
    
    Args:
        chapter_lines: チャプター行のリスト
        
    Returns:
        有効な場合はTrue
    """
    for line in chapter_lines:
        if not line.strip():
            continue
            
        # MM:SS 形式を検証
        time_match = re.match(r'^(\d{1,2}):(\d{2})\s+(.+)$', line.strip())
        if not time_match:
            return False
        
        minutes, seconds, title = time_match.groups()
        
        # 時間の妥当性チェック
        try:
            min_val = int(minutes)
            sec_val = int(seconds)
            if sec_val >= 60 or min_val < 0:
                return False
        except ValueError:
            return False
        
        # タイトルに問題文字が含まれていないか
        if CHAPTER_PROBLEMATIC.search(title):
            return False
    
    return True


def filter_emojis(text: str) -> str:
    """絵文字をフィルタリング（許可リストのみ保持）
    
    Args:
        text: フィルタリングするテキスト
        
    Returns:
        フィルタリングされたテキスト
    """
    if not text:
        return ""
    
    # 許可された絵文字以外を削除
    filtered_chars = []
    for char in text:
        # 許可された絵文字か、絵文字でない文字は保持
        if char in ALLOWED_EMOJIS or not unicodedata.category(char).startswith('So'):
            filtered_chars.append(char)
    
    return ''.join(filtered_chars)
