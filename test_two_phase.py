"""2段階生成の簡易テスト"""
import asyncio
from pathlib import Path
from core.models import load_config
from core.models.curation import CuratedTopic
from services.script_generation.segment_generator import SegmentGenerator
from services.script_generation.adapters.factory import LLMAdapterFactory

async def test_two_phase_generation():
    """2段階生成モードのテスト"""
    print("=" * 80)
    print("2段階生成モード テスト開始")
    print("=" * 80)
    
    # Config読み込み
    project_root = Path(__file__).parent
    config = load_config(project_root)
    
    # 2段階生成が有効か確認
    two_phase = getattr(config.yaml.script_generator.orchestrator, 'two_phase_generation', False)
    print(f"\n✓ 2段階生成モード: {two_phase}")
    
    # LLM Port作成（Ollama）
    provider = "ollama"
    llm_port = LLMAdapterFactory.create(config, provider)
    print(f"✓ LLM Port作成: {provider}")
    
    # SegmentGenerator作成
    generator = SegmentGenerator(llm_port, config)
    print(f"✓ SegmentGenerator作成")
    print(f"  - two_phase_enabled: {generator.two_phase_enabled}")
    print(f"  - segment_model: {generator.segment_model}")
    
    # テスト用のイントロ生成
    print("\n" + "=" * 80)
    print("イントロセグメント生成テスト")
    print("=" * 80)
    
    theme = "Gemma4"
    topic_titles = ["Gemma4の特徴", "オンデバイスAIの可能性"]
    
    try:
        segment = await generator.generate_intro(
            theme=theme,
            topic_titles=topic_titles,
            context="",
            progress_log=print
        )
        
        print(f"\n✓ 生成成功！")
        print(f"  - ターン数: {len(segment.turns)}")
        print(f"  - 最初のターン: {segment.turns[0] if segment.turns else 'なし'}")
        print(f"  - Usage: {generator.last_usage}")
        
    except Exception as e:
        print(f"\n✗ エラー発生: {e}")
        import traceback
        traceback.print_exc()
    
    print("\n" + "=" * 80)
    print("テスト完了")
    print("=" * 80)

if __name__ == "__main__":
    asyncio.run(test_two_phase_generation())
