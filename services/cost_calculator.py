"""APIコスト計算サービス"""
from dataclasses import dataclass
from typing import Optional

from core.models.usage import (
    TotalUsage,
    CostBreakdown,
    PerplexityUsage,
    GeminiUsage,
)


@dataclass
class CostRates:
    """APIコストレート（USD）"""
    # Perplexity: $0.005 per request
    perplexity_per_request: float = 0.005
    
    # Gemini 3.0 Pro (仮定レート)
    # Input: $1.25 / 1M tokens
    # Output: $5.00 / 1M tokens
    gemini_input_per_million: float = 1.25
    gemini_output_per_million: float = 5.00
    
    # VOICEVOX: $0.00 (Local)
    voicevox_per_phrase: float = 0.00
    
    # USD to JPY レート
    usd_to_jpy: float = 150.0


class CostCalculator:
    """APIコスト計算クラス"""
    
    def __init__(self, rates: Optional[CostRates] = None):
        self.rates = rates or CostRates()
    
    def calculate(self, usage: TotalUsage) -> CostBreakdown:
        """使用量からコストを計算
        
        Args:
            usage: 全API使用量
        
        Returns:
            CostBreakdown: コスト内訳
        """
        # Perplexity コスト
        perplexity_usd = (
            usage.perplexity.request_count * self.rates.perplexity_per_request
        )
        
        # Gemini コスト
        gemini_input_usd = (
            usage.gemini.input_tokens / 1_000_000 * self.rates.gemini_input_per_million
        )
        gemini_output_usd = (
            usage.gemini.output_tokens / 1_000_000 * self.rates.gemini_output_per_million
        )
        
        # VOICEVOX（無料）
        voicevox_usd = 0.0
        
        # 合計
        total_usd = perplexity_usd + gemini_input_usd + gemini_output_usd + voicevox_usd
        total_jpy = total_usd * self.rates.usd_to_jpy
        
        # 無料枠判定（Gemini無料枠: 月15リクエスト/分、1日1500リクエスト）
        is_free_tier = self._check_free_tier(usage)
        free_tier_note = ""
        if is_free_tier:
            free_tier_note = "Gemini Free Tier適用中（月間上限あり）"
        
        return CostBreakdown(
            perplexity_usd=perplexity_usd,
            gemini_input_usd=gemini_input_usd,
            gemini_output_usd=gemini_output_usd,
            voicevox_usd=voicevox_usd,
            total_usd=total_usd,
            total_jpy=total_jpy,
            is_free_tier=is_free_tier,
            free_tier_note=free_tier_note,
        )
    
    def _check_free_tier(self, usage: TotalUsage) -> bool:
        """無料枠かどうかを判定（簡易的）"""
        # Gemini Free Tierの条件は複雑なため、
        # ここでは単純に1リクエストなら無料枠と仮定
        return usage.gemini.request_count <= 1
    
    def format_cost_report(self, usage: TotalUsage, cost: CostBreakdown) -> str:
        """コストレポートをMarkdown形式でフォーマット
        
        Args:
            usage: 使用量
            cost: コスト内訳
        
        Returns:
            str: Markdown形式のレポート
        """
        lines = [
            "## 📊 API使用量・コストレポート",
            "",
            "### 使用量",
            f"| サービス | 使用量 |",
            f"|----------|--------|",
        ]
        
        # Perplexity
        if usage.perplexity.request_count > 0:
            lines.append(
                f"| Perplexity | {usage.perplexity.request_count} リクエスト |"
            )
        
        # Gemini
        if usage.gemini.total_tokens > 0:
            lines.append(
                f"| Gemini ({usage.gemini.model_name}) | "
                f"入力 {usage.gemini.input_tokens:,} / 出力 {usage.gemini.output_tokens:,} tokens |"
            )
            
            # 参考文献候補によるトークン増分を表示
            ref_overhead = usage.gemini.input_tokens - 264  # 推定ベースライン
            if ref_overhead > 0:
                lines.append(
                    f"|  ├─ 参考文献候補 | +{ref_overhead:,} tokens (推定: 264) |"
                )
        
        # VOICEVOX
        if usage.voicevox.phrase_count > 0:
            lines.append(
                f"| VOICEVOX (Local) | {usage.voicevox.phrase_count} フレーズ "
                f"({usage.voicevox.total_duration_sec:.1f}秒) |"
            )
        
        lines.extend([
            "",
            "### 推定コスト",
            f"| 項目 | コスト (USD) |",
            f"|------|-------------|",
        ])
        
        if usage.perplexity.request_count > 0:
            lines.append(f"| Perplexity | ${cost.perplexity_usd:.4f} |")
        
        if usage.gemini.total_tokens > 0:
            gemini_total = cost.gemini_input_usd + cost.gemini_output_usd
            free_note = " (Free Tier)" if cost.is_free_tier else ""
            lines.append(f"| Gemini{free_note} | ${gemini_total:.4f} |")
        
        lines.append(f"| VOICEVOX | $0.00 (無料) |")
        
        lines.extend([
            f"| **合計** | **${cost.total_usd:.4f}** (約{cost.total_jpy:.0f}円) |",
        ])
        
        if cost.free_tier_note:
            lines.extend(["", f"*{cost.free_tier_note}*"])
        
        # 処理時間
        if usage.total_duration_sec > 0:
            lines.extend([
                "",
                "### 処理時間",
                f"| フェーズ | 時間 |",
                f"|----------|------|",
            ])
            if usage.research_duration_sec > 0:
                lines.append(f"| リサーチ | {usage.research_duration_sec:.1f}秒 |")
            if usage.script_duration_sec > 0:
                lines.append(f"| 台本生成 | {usage.script_duration_sec:.1f}秒 |")
            if usage.audio_duration_sec > 0:
                lines.append(f"| 音声合成 | {usage.audio_duration_sec:.1f}秒 |")
            if usage.render_duration_sec > 0:
                lines.append(f"| 動画生成 | {usage.render_duration_sec:.1f}秒 |")
            lines.append(f"| **合計** | **{usage.total_duration_sec:.1f}秒** |")
        
        return "\n".join(lines)
