"""APIコスト計算サービス（SSOT対応版）"""
import logging
from typing import Optional
from core.models.config import AppConfig
from core.models.usage import (
    TotalUsage,
    CostBreakdown,
    PerplexityUsage,
    LLMUsage,
)

logger = logging.getLogger(__name__)

# Free-tier detection bounds (Gemini).
# Lower bound ensures zero-request runs are NOT flagged as free-tier.
_FREE_TIER_MIN_REQUESTS = 1
_FREE_TIER_MAX_REQUESTS = 1

# Backward compatibility alias
GeminiUsage = LLMUsage


class CostCalculator:
    """API cost calculator using AppConfig as SSOT
    
    Retrieves cost rates directly from config.yaml (via AppConfig)
    instead of external costs.yaml file.
    """
    
    def __init__(self, config: AppConfig):
        """Initialize with AppConfig
        
        Args:
            config: Application configuration (SSOT)
        """
        self.config = config
        self.usd_to_jpy = config.yaml.script_generator.currency.usd_to_jpy
    
    def get_llm_rate(self, provider: str, model_name: str) -> tuple[float, float]:
        """Get input/output rates for a specific model
        
        Args:
            provider: Provider name ("gemini" | "openai" | "anthropic" | "ollama")
            model_name: LLM model name (e.g., "gpt-4o-mini")
        
        Returns:
            tuple[float, float]: (input_rate, output_rate) per 1M tokens
        """
        # Use provider directly instead of inferring from model name
        
        # Ollama is local, zero cost
        if provider == "ollama":
            return 0.0, 0.0
        
        # Get cost data from config
        if provider == "gemini":
            costs = self.config.yaml.script_generator.gemini.costs
        elif provider == "openai":
            costs = self.config.yaml.script_generator.openai.costs
        elif provider == "anthropic":
            costs = self.config.yaml.script_generator.anthropic.costs
        else:
            # Fallback to gemini costs
            costs = self.config.yaml.script_generator.gemini.costs
        
        # Get model cost
        model_cost = costs.get(model_name)
        if model_cost is None:
            # Fallback to first available model in provider
            if costs:
                fallback_model_name = next(iter(costs.keys()))
                model_cost = costs[fallback_model_name]
                logger.warning(
                    "Unknown model '%s' for provider '%s'. "
                    "Falling back to '%s' pricing (input=%.4f, output=%.4f per 1M tokens). "
                    "Cost estimates may be inaccurate — please register this model in config.yaml.",
                    model_name, provider, fallback_model_name,
                    model_cost.input, model_cost.output,
                )
            else:
                # Ultimate fallback (gemini-2.5-flash rates)
                from core.models.config import ModelCost
                model_cost = ModelCost(input=0.30, output=2.50)
                logger.warning(
                    "No cost data available for provider '%s' (model '%s'). "
                    "Using hard-coded fallback rates (input=0.30, output=2.50 per 1M tokens).",
                    provider, model_name,
                )

        return model_cost.input, model_cost.output
    
    def get_all_available_models(self) -> list[str]:
        """Get all available models from config
        
        Returns:
            list[str]: List of all model names with cost data
        """
        models = []
        models.extend(self.config.yaml.script_generator.gemini.costs.keys())
        models.extend(self.config.yaml.script_generator.openai.costs.keys())
        models.extend(self.config.yaml.script_generator.anthropic.costs.keys())
        # Add Ollama model if configured
        if self.config.yaml.script_generator.ollama.model:
            models.append(self.config.yaml.script_generator.ollama.model)
        return models
    
    def calculate(self, usage: TotalUsage) -> CostBreakdown:
        """Calculate costs from usage with per-provider, per-model rates
        
        Args:
            usage: Total API usage
        
        Returns:
            CostBreakdown: Cost breakdown
        """
        # Perplexity cost (fixed rate: $0.005 per request)
        perplexity_per_request = 0.005
        perplexity_usd = usage.perplexity.request_count * perplexity_per_request
        
        # LLM costs (per-provider aggregation)
        total_llm_input_usd = 0.0
        total_llm_output_usd = 0.0
        
        for provider, llm_usage in usage.llm_usage.items():
            input_rate, output_rate = self.get_llm_rate(provider, llm_usage.model_name)
            total_llm_input_usd += (llm_usage.input_tokens / 1_000_000) * input_rate
            total_llm_output_usd += (llm_usage.output_tokens / 1_000_000) * output_rate
        
        # VOICEVOX (free)
        voicevox_usd = 0.0
        
        # Total
        total_usd = perplexity_usd + total_llm_input_usd + total_llm_output_usd + voicevox_usd
        total_jpy = total_usd * self.usd_to_jpy
        
        # Free tier check (simplified)
        is_free_tier = self._check_free_tier(usage)
        free_tier_note = ""
        if is_free_tier:
            free_tier_note = "Gemini Free Tier適用中（月間上限あり）"
        
        return CostBreakdown(
            perplexity_usd=perplexity_usd,
            gemini_input_usd=total_llm_input_usd,  # Reusing field for all LLM input
            gemini_output_usd=total_llm_output_usd,  # Reusing field for all LLM output
            voicevox_usd=voicevox_usd,
            total_usd=total_usd,
            total_jpy=total_jpy,
            is_free_tier=is_free_tier,
            free_tier_note=free_tier_note,
        )
    
    def _check_free_tier(self, usage: TotalUsage) -> bool:
        """Check if usage qualifies for free tier (simplified).

        Gemini Free Tier conditions are complex; we approximate by flagging
        runs with a small, non-zero Gemini request count. A zero request
        count means Gemini was not used at all and therefore must NOT be
        displayed as "Free Tier applied".
        """
        gemini_usage = usage.llm_usage.get("gemini")
        if gemini_usage is None:
            return False
        return (
            _FREE_TIER_MIN_REQUESTS
            <= gemini_usage.request_count
            <= _FREE_TIER_MAX_REQUESTS
        )
    
    def format_llm_cost_log(self, usage: LLMUsage) -> list[str]:
        """Format LLM usage and cost as log lines
        
        Args:
            usage: LLM usage data
        
        Returns:
            list[str]: List of log lines
        """
        input_rate, output_rate = self.get_llm_rate(usage.provider, usage.model_name)
        cost_usd = (
            (usage.input_tokens / 1_000_000) * input_rate +
            (usage.output_tokens / 1_000_000) * output_rate
        )
        cost_jpy = cost_usd * self.usd_to_jpy
        
        return [
            "",
            "【使用量・コスト】",
            f"{usage.provider.upper()}: {usage.model_name}",
            f"  入力トークン: {usage.input_tokens:,}",
            f"  出力トークン: {usage.output_tokens:,}",
            f"  コスト: ${cost_usd:.4f} (約{cost_jpy:.1f}円)"
        ]
    
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
        
        # LLM usage (per-provider)
        for provider, llm_usage in usage.llm_usage.items():
            if llm_usage.total_tokens > 0:
                lines.append(
                    f"| {provider.upper()} ({llm_usage.model_name}) | "
                    f"入力 {llm_usage.input_tokens:,} / 出力 {llm_usage.output_tokens:,} tokens |"
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
        
        # LLM costs (per-provider)
        for provider, llm_usage in usage.llm_usage.items():
            if llm_usage.total_tokens > 0:
                input_rate, output_rate = self.get_llm_rate(provider, llm_usage.model_name)
                provider_cost = (
                    (llm_usage.input_tokens / 1_000_000) * input_rate +
                    (llm_usage.output_tokens / 1_000_000) * output_rate
                )
                free_note = " (Free Tier)" if cost.is_free_tier and provider == "gemini" else ""
                lines.append(f"| {provider.upper()}{free_note} | ${provider_cost:.4f} |")
        
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
            
            # Add image generation times if present
            if usage.segment_bg_generation_time > 0:
                lines.append(f"| セグメント背景生成 | {usage.segment_bg_generation_time:.1f}秒 |")
            if usage.thumbnail_bg_generation_time > 0:
                lines.append(f"| サムネイル背景生成 | {usage.thumbnail_bg_generation_time:.1f}秒 |")
            
            if usage.render_duration_sec > 0:
                lines.append(f"| 動画生成 | {usage.render_duration_sec:.1f}秒 |")
            lines.append(f"| **合計** | **{usage.total_duration_sec:.1f}秒** |")
        
        return "\n".join(lines)
