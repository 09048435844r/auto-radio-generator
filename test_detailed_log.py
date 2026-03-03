#!/usr/bin/env python3
"""詳細なログ分析用スクリプト"""

from app import generate_video
import gradio as gr

def test_detailed_log():
    print('=== DETAILED LOG ANALYSIS ===')
    
    # 2階建てモードで動画生成を実行
    result = generate_video(
        theme='AIの未来について',
        research_mode='トリビア (雑学)',
        background_image='default.png',
        bgm_file='【朝・昼向け】爽やかなアコースティック.mp3',
        bgm_volume=0.1,
        fade_time=3.0,
        speed_scale=1.0,
        enable_spectrum=True,
        avoid_topics='',
        upload_to_youtube=False,
        footer_text='',
        use_mock=False,
        second_mode='ディベート (賛否両論)',
        jingle_choice='なし',
        jingle_custom_path='',
        progress=gr.Progress()
    )
    
    log_content = result[1]
    
    print('Log preview (safe output):')
    try:
        print(log_content[:500].encode('ascii', 'replace').decode('ascii'))
    except:
        print('[Log contains non-ASCII characters]')
    print('...')
    
    print('Checking for specific patterns...')
    patterns = [
        '第2部モード有効',
        '第1部の全量コンテキスト',
        '--- 第1部 放送済み ---',
        '第2部モード: 第1部コンテキストを適用',
        '台本結合完了'
    ]
    
    for pattern in patterns:
        found = "FOUND" if pattern in log_content else "NOT FOUND"
        print(f'{pattern}: {found}')

if __name__ == '__main__':
    test_detailed_log()
