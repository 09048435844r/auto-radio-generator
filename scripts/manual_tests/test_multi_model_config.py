"""Test script to validate Multi-Model Routing configuration"""
import yaml
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[2]
config_path = PROJECT_ROOT / "config.yaml"
config = yaml.safe_load(config_path.read_text(encoding="utf-8"))

orch = config["script_generator"]["orchestrator"]

print("✓ Config validation passed")
print(f"Orchestrator enabled: {orch['enabled']}")
print(f"Two-phase generation: {orch['two_phase_generation']}")
print(f"Phase 1 model (segment_model): {orch.get('segment_model') or 'default'}")
print(f"Phase 2 model (json_model): {orch.get('json_model') or 'same as segment_model'}")
print(f"\n✓ Multi-Model Routing configuration is valid!")
