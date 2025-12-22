"""VOICEVOX話者一覧を確認するスクリプト"""
import sys
import httpx

# Windows用文字コード設定
sys.stdout.reconfigure(encoding='utf-8')

response = httpx.get("http://localhost:50021/speakers")
speakers = response.json()

print("=" * 60)
print("VOICEVOX 利用可能な話者一覧")
print("=" * 60)

for speaker in speakers:
    print(f"\n【{speaker['name']}】")
    for style in speaker['styles']:
        print(f"  ID: {style['id']:3d} - {style['name']}")
