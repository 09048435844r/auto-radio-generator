"""Comparison session persistence service

Handles saving and loading of LLM comparison sessions with complete snapshots
including research data, scripts, usage data, and comparison reports.
"""
import json
from pathlib import Path
from datetime import datetime
from typing import List, Dict, Any, Optional
from dataclasses import dataclass, asdict

from core.models import AppConfig, LLMUsage


@dataclass
class ComparisonSession:
    """Comparison session metadata"""
    session_id: str
    theme: str
    created_at: str
    models_compared: List[str]
    total_cost_usd: float
    total_cost_jpy: float


def save_comparison_session(
    comparison_state: List[dict],
    research_data: Dict[str, Any],
    theme: str,
    config: AppConfig
) -> str:
    """Save complete comparison session snapshot to disk
    
    Args:
        comparison_state: List of comparison data from gr.State
            [
                {
                    "model_name": "gemini-2.5-pro",
                    "script_json": "...",
                    "usage": LLMUsage(...)
                },
                ...
            ]
        research_data: Research input data
            {
                "theme": "...",
                "content": "...",
                "timestamp": "..."
            }
        theme: Session theme/title
        config: Application configuration
    
    Returns:
        str: Path to saved session directory
    
    Raises:
        ValueError: If comparison_state has less than 2 models
    """
    if len(comparison_state) < 2:
        raise ValueError("Comparison session requires at least 2 models")
    
    # Ensure theme is a string
    if not isinstance(theme, str):
        raise TypeError(f"theme must be a string, got {type(theme).__name__}")
    
    # Create session directory
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    theme_str = theme.strip() if theme else "untitled"
    safe_theme = "".join(c for c in theme_str[:30] if c.isalnum() or c in (' ', '_')).replace(' ', '_')
    session_dir = Path("data") / "comparisons" / f"{timestamp}_{safe_theme}"
    session_dir.mkdir(parents=True, exist_ok=True)
    
    # Create scripts subdirectory
    scripts_dir = session_dir / "scripts"
    scripts_dir.mkdir(exist_ok=True)
    
    # Extract model names and calculate total costs
    from services.cost_calculator import CostCalculator
    calculator = CostCalculator(config)
    
    models_compared = []
    total_cost_usd = 0.0
    usage_data = {}
    
    for data in comparison_state:
        model_name = data["model_name"]
        models_compared.append(model_name)
        
        # Save individual script JSON
        script_file = scripts_dir / f"{model_name}.json"
        with open(script_file, "w", encoding="utf-8") as f:
            f.write(data["script_json"])
        
        # Extract usage data
        usage: LLMUsage = data["usage"]
        input_rate, output_rate = calculator.get_llm_rate(usage.provider, usage.model_name)
        cost_usd = (
            (usage.input_tokens / 1_000_000) * input_rate +
            (usage.output_tokens / 1_000_000) * output_rate
        )
        cost_jpy = cost_usd * calculator.usd_to_jpy
        
        total_cost_usd += cost_usd
        
        usage_data[model_name] = {
            "model_name": usage.model_name,
            "provider": usage.provider,
            "input_tokens": usage.input_tokens,
            "output_tokens": usage.output_tokens,
            "request_count": usage.request_count,
            "cost_usd": cost_usd,
            "cost_jpy": cost_jpy
        }
    
    total_cost_jpy = total_cost_usd * calculator.usd_to_jpy
    
    # Save session metadata
    session_metadata = ComparisonSession(
        session_id=timestamp,
        theme=theme,
        created_at=datetime.now().isoformat(),
        models_compared=models_compared,
        total_cost_usd=total_cost_usd,
        total_cost_jpy=total_cost_jpy
    )
    
    metadata_file = session_dir / "session_metadata.json"
    with open(metadata_file, "w", encoding="utf-8") as f:
        json.dump(asdict(session_metadata), f, ensure_ascii=False, indent=2)
    
    # Save research input
    research_file = session_dir / "research_input.jsonl"
    with open(research_file, "w", encoding="utf-8") as f:
        f.write(json.dumps(research_data, ensure_ascii=False) + "\n")
    
    # Save usage data
    usage_file = session_dir / "usage_data.json"
    with open(usage_file, "w", encoding="utf-8") as f:
        json.dump(usage_data, f, ensure_ascii=False, indent=2)
    
    # Generate and save comparison report
    from services.comparison_report import generate_comparison_report
    comparison_report_md = generate_comparison_report(comparison_state, config)
    
    report_file = session_dir / "comparison_report.md"
    with open(report_file, "w", encoding="utf-8") as f:
        f.write(comparison_report_md)
    
    return str(session_dir)


def load_comparison_session(session_path: str) -> Optional[Dict[str, Any]]:
    """Load comparison session from disk (future extension)
    
    Args:
        session_path: Path to session directory
    
    Returns:
        Dict containing session data or None if not found
    """
    session_dir = Path(session_path)
    if not session_dir.exists():
        return None
    
    # Load metadata
    metadata_file = session_dir / "session_metadata.json"
    if not metadata_file.exists():
        return None
    
    with open(metadata_file, "r", encoding="utf-8") as f:
        metadata = json.load(f)
    
    # Load scripts
    scripts_dir = session_dir / "scripts"
    scripts = {}
    for script_file in scripts_dir.glob("*.json"):
        model_name = script_file.stem
        with open(script_file, "r", encoding="utf-8") as f:
            scripts[model_name] = f.read()
    
    # Load usage data
    usage_file = session_dir / "usage_data.json"
    with open(usage_file, "r", encoding="utf-8") as f:
        usage_data = json.load(f)
    
    # Load research input
    research_file = session_dir / "research_input.jsonl"
    with open(research_file, "r", encoding="utf-8") as f:
        research_data = json.loads(f.readline())
    
    # Load comparison report
    report_file = session_dir / "comparison_report.md"
    with open(report_file, "r", encoding="utf-8") as f:
        comparison_report = f.read()
    
    return {
        "metadata": metadata,
        "scripts": scripts,
        "usage_data": usage_data,
        "research_data": research_data,
        "comparison_report": comparison_report
    }
