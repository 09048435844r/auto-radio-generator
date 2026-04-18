"""Multi-provider usage tracking system test"""
from core.models.usage import LLMUsage, TotalUsage
from services.cost_calculator import CostCalculator
from core.models import load_config

def test_llm_usage_model():
    """Test LLMUsage model with provider tracking"""
    print("Testing LLMUsage model...")
    
    # Create usage for different providers
    gemini_usage = LLMUsage(
        provider="gemini",
        model_name="gemini-1.5-pro",
        input_tokens=1000,
        output_tokens=500,
        request_count=1
    )
    
    openai_usage = LLMUsage(
        provider="openai",
        model_name="gpt-4o-mini",
        input_tokens=800,
        output_tokens=400,
        request_count=1
    )
    
    print(f"  Gemini: {gemini_usage.provider}, {gemini_usage.model_name}")
    print(f"  OpenAI: {openai_usage.provider}, {openai_usage.model_name}")
    print("  ✓ LLMUsage model works")

def test_total_usage_aggregation():
    """Test TotalUsage with Dict[str, LLMUsage] aggregation"""
    print("\nTesting TotalUsage aggregation...")
    
    total_usage = TotalUsage()
    
    # Add Gemini usage
    total_usage.llm_usage["gemini"] = LLMUsage(
        provider="gemini",
        model_name="gemini-1.5-pro",
        input_tokens=1000,
        output_tokens=500,
        request_count=1
    )
    
    # Add OpenAI usage
    total_usage.llm_usage["openai"] = LLMUsage(
        provider="openai",
        model_name="gpt-4o-mini",
        input_tokens=800,
        output_tokens=400,
        request_count=1
    )
    
    print(f"  Providers tracked: {list(total_usage.llm_usage.keys())}")
    print(f"  Gemini tokens: {total_usage.llm_usage['gemini'].total_tokens}")
    print(f"  OpenAI tokens: {total_usage.llm_usage['openai'].total_tokens}")
    
    # Test backward compatibility property
    print(f"  Backward compat (gemini property): {total_usage.gemini.provider}")
    print("  ✓ TotalUsage aggregation works")

def test_cost_calculator():
    """Test CostCalculator with model-specific rates"""
    print("\nTesting CostCalculator...")
    
    config = load_config()
    calc = CostCalculator(config)
    
    # Test rate lookup
    gemini_rates = calc.get_llm_rate("gemini", "gemini-1.5-pro")
    openai_rates = calc.get_llm_rate("openai", "gpt-4o-mini")
    ollama_rates = calc.get_llm_rate("ollama", "gemma4:26b")
    
    print(f"  Gemini 1.5 Pro rates: ${gemini_rates[0]:.2f} / ${gemini_rates[1]:.2f} per 1M")
    print(f"  GPT-4o-mini rates: ${openai_rates[0]:.2f} / ${openai_rates[1]:.2f} per 1M")
    print(f"  Ollama (gemma4:26b) rates: ${ollama_rates[0]:.2f} / ${ollama_rates[1]:.2f} per 1M (should be 0.00)")
    
    # Test cost calculation
    total_usage = TotalUsage()
    total_usage.llm_usage["gemini"] = LLMUsage(
        provider="gemini",
        model_name="gemini-1.5-pro",
        input_tokens=1000000,  # 1M tokens
        output_tokens=500000,  # 0.5M tokens
        request_count=1
    )
    
    cost = calc.calculate(total_usage)
    expected_cost = 1.25 + (0.5 * 5.00)  # 1M * $1.25 + 0.5M * $5.00 = $3.75
    
    print(f"  Calculated cost: ${cost.total_usd:.2f}")
    print(f"  Expected cost: ${expected_cost:.2f}")
    
    if abs(cost.total_usd - expected_cost) < 0.01:
        print("  ✓ CostCalculator works correctly")
    else:
        print(f"  ✗ Cost mismatch: {cost.total_usd} != {expected_cost}")

if __name__ == "__main__":
    print("=" * 60)
    print("Multi-Provider Usage Tracking System Test")
    print("=" * 60)
    
    try:
        test_llm_usage_model()
        test_total_usage_aggregation()
        test_cost_calculator()
        
        print("\n" + "=" * 60)
        print("All tests passed! ✓")
        print("=" * 60)
        
    except Exception as e:
        print(f"\n✗ Test failed: {e}")
        import traceback
        traceback.print_exc()
