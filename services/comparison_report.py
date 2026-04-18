"""Script comparison report generation service"""
from dataclasses import dataclass
from typing import List
import json


@dataclass
class ScriptComparison:
    """Script comparison data"""
    model_name: str
    turn_count: int
    estimated_duration_sec: float
    input_tokens: int
    output_tokens: int
    cost_usd: float
    cost_jpy: float


def generate_comparison_report(scripts_data: List[dict], config) -> str:
    """Generate comparison report from multiple script data
    
    Args:
        scripts_data: List of script data
            [
                {
                    "model_name": "gemini-3.1-pro-preview",
                    "script_json": "...",
                    "usage": LLMUsage(...)
                },
                ...
            ]
        config: Application configuration (AppConfig)
    
    Returns:
        str: Comparison report in Markdown format
    """
    from services.cost_calculator import CostCalculator
    
    comparisons = []
    calculator = CostCalculator(config)
    
    for data in scripts_data:
        script = json.loads(data["script_json"])
        usage = data["usage"]
        
        # Estimate video duration (assume ~7 seconds per turn)
        turn_count = len(script.get("dialogue", []))
        estimated_duration = turn_count * 7.0
        
        # Calculate cost
        input_rate, output_rate = calculator.get_llm_rate(usage.provider, usage.model_name)
        cost_usd = (
            (usage.input_tokens / 1_000_000) * input_rate +
            (usage.output_tokens / 1_000_000) * output_rate
        )
        cost_jpy = cost_usd * calculator.usd_to_jpy  # SSOT: use config-driven rate
        
        comparisons.append(ScriptComparison(
            model_name=usage.model_name,
            turn_count=turn_count,
            estimated_duration_sec=estimated_duration,
            input_tokens=usage.input_tokens,
            output_tokens=usage.output_tokens,
            cost_usd=cost_usd,
            cost_jpy=cost_jpy
        ))
    
    # Generate report (スケーラブルなヘッダー)
    lines = [
        f"# 📊 台本比較レポート（{len(comparisons)} モデル）",
        "",
        "## 基本情報",
        "",
        "| モデル | ターン数 | 推定動画長 | 入力トークン | 出力トークン | コスト (USD) | コスト (円) |",
        "|--------|---------|----------|------------|------------|------------|-----------|"
    ]
    
    for comp in comparisons:
        duration_min = int(comp.estimated_duration_sec // 60)
        duration_sec = int(comp.estimated_duration_sec % 60)
        
        lines.append(
            f"| {comp.model_name} | "
            f"{comp.turn_count} | "
            f"{duration_min}分{duration_sec}秒 | "
            f"{comp.input_tokens:,} | "
            f"{comp.output_tokens:,} | "
            f"${comp.cost_usd:.4f} | "
            f"¥{comp.cost_jpy:.1f} |"
        )
    
    # Statistics
    if len(comparisons) >= 2:
        lines.extend([
            "",
            "## 統計",
            "",
            f"- **最長台本**: {max(comparisons, key=lambda x: x.turn_count).model_name} ({max(c.turn_count for c in comparisons)}ターン)",
            f"- **最短台本**: {min(comparisons, key=lambda x: x.turn_count).model_name} ({min(c.turn_count for c in comparisons)}ターン)",
            f"- **最安コスト**: {min(comparisons, key=lambda x: x.cost_usd).model_name} (${min(c.cost_usd for c in comparisons):.4f})",
            f"- **最高コスト**: {max(comparisons, key=lambda x: x.cost_usd).model_name} (${max(c.cost_usd for c in comparisons):.4f})",
        ])
    
    return "\n".join(lines)
