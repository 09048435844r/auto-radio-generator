#!/usr/bin/env python3
"""2階建てモードのログ検証用スクリプト"""

from app import generate_video
import gradio as gr

def test_log_verification():
    print('=== LOG VERIFICATION ===')
    
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
    
    print('Checking for full transcript in logs...')
    
    # 全量トランスクリプトのセパレーターをチェック
    if '--- 第1部 放送済み ---' in log_content:
        print('[OK] Full transcript delimiter found in logs')
    else:
        print('[NG] Full transcript delimiter NOT found')
    
    # 第2部モードのログをチェック
    if '第2部モード: 第1部コンテキストを適用' in log_content:
        print('[OK] Part2 mode log found')
    else:
        print('[NG] Part2 mode log NOT found')
    
    # ワークフローのログをチェック
    if '第1部の全量コンテキストを第2部へ渡しました' in log_content:
        print('[OK] Workflow full context log found')
    else:
        print('[NG] Workflow full context log NOT found')
    
    # 台本結合のログをチェック
    if '台本結合完了' in log_content:
        print('[OK] Script merging log found')
    else:
        print('[NG] Script merging log NOT found')

if __name__ == '__main__':
    test_log_verification()
