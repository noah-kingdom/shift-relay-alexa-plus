from pathlib import Path
import json
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from shift_relay.demo import DemoScenario  # noqa: E402


def main() -> None:
    demo = DemoScenario(ROOT / "shiftrelay-cli-demo.db")
    result = demo.run_full()
    for i, step in enumerate(result["steps"], 1):
        print(f"\n[{i}] {step['name']}")
        if step.get("utterance"):
            print("USER:", step["utterance"])
        if step.get("spoken"):
            print("ALEXA+:", step["spoken"])
    print("\nFINAL STATE")
    print(json.dumps(result["snapshot"], indent=2))


if __name__ == "__main__":
    main()
