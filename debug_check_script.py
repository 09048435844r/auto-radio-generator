import json
from pathlib import Path

script_file = Path("workspace/20260406_104420/script_artifact.json")
if script_file.exists():
    with open(script_file, encoding='utf-8') as f:
        data = json.load(f)
    
    sections = data['script']['sections']
    dialogue_turns = [s for s in sections if s.get('speaker')]
    
    print(f"Total sections: {len(sections)}")
    print(f"Dialogue turns: {len(dialogue_turns)}")
    print(f"\nFirst 3 dialogue turns:")
    for i, turn in enumerate(dialogue_turns[:3], 1):
        print(f"{i}. {turn['speaker']}: {turn['text'][:60]}...")
else:
    print(f"File not found: {script_file}")
