"""URLからウェブページのタイトルを取得するユーティリティ"""
import asyncio
import concurrent.futures
import logging
from urllib.parse import urlparse

import requests
from bs4 import BeautifulSoup
import chardet

from services.publishing.text_sanitizer import sanitize_title

logger = logging.getLogger(__name__)

# ユーザーエージェント（一般的なブラウザを模倣）
USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/120.0.0.0 Safari/537.36"
)

# タイムアウト設定（秒）
REQUEST_TIMEOUT = 3


def fetch_page_title(url: str) -> str:
    """URLからウェブページの<title>タグを取得する
    
    Args:
        url: ウェブページのURL
        
    Returns:
        ページタイトル。取得失敗時はドメイン名を返す
    """
    try:
        # URLを正規化
        if not url.startswith(('http://', 'https://')):
            url = f'https://{url}'
        
        # リクエスト送信
        response = requests.get(
            url,
            headers={'User-Agent': USER_AGENT},
            timeout=REQUEST_TIMEOUT,
            allow_redirects=True
        )
        response.raise_for_status()
        
        # エンコーディング検出とデコード
        detected_encoding = None
        if 'content-type' in response.headers:
            content_type = response.headers['content-type']
            if 'charset=' in content_type:
                detected_encoding = content_type.split('charset=')[1].strip()
        
        if not detected_encoding:
            # chardetでエンコーディングを検出
            detected = chardet.detect(response.content)
            detected_encoding = detected.get('encoding', 'utf-8')
        
        # HTMLをデコード（エラー時はreplace）
        try:
            html = response.content.decode(detected_encoding or 'utf-8', errors='replace')
        except (UnicodeDecodeError, LookupError):
            html = response.content.decode('utf-8', errors='replace')
        
        # HTMLパースして<title>を抽出
        soup = BeautifulSoup(html, 'html.parser')
        title_tag = soup.find('title')
        
        if title_tag and title_tag.string:
            title = title_tag.string.strip()
            # タイトルが空または短すぎる場合はフォールバック
            if len(title) >= 3:
                # サニタイズして返す
                sanitized = sanitize_title(title)
                if sanitized:
                    return sanitized
        
        # フォールバック: ドメイン名
        parsed = urlparse(url)
        return parsed.netloc or url
        
    except requests.exceptions.Timeout:
        logger.warning(f"Title fetch timeout for {url}")
    except requests.exceptions.HTTPError as e:
        logger.warning(f"Title fetch HTTP error for {url}: {e}")
    except Exception as e:
        logger.warning(f"Title fetch failed for {url}: {e}")
    
    # 例外発生時はフォールバック: ドメイン名
    try:
        parsed = urlparse(url)
        return parsed.netloc or url
    except Exception:
        return url


async def fetch_page_titles_async(urls: list[str]) -> list[str]:
    """複数のURLから並列でページタイトルを取得する
    
    Args:
        urls: ウェブページのURLリスト
        
    Returns:
        ページタイトルのリスト（URLと同じ順序）
    """
    if not urls:
        return []
    
    # ThreadPoolExecutorで並列実行
    loop = asyncio.get_event_loop()
    with concurrent.futures.ThreadPoolExecutor(max_workers=10) as executor:
        tasks = [
            loop.run_in_executor(executor, fetch_page_title, url)
            for url in urls
        ]
        titles = await asyncio.gather(*tasks, return_exceptions=False)
    
    return titles


def fetch_page_title_sync(url: str) -> str:
    """同期版のタイトル取得（既存コードとの互換性用）"""
    return fetch_page_title(url)
