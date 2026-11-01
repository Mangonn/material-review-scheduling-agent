"""Collect real-model conflict and risk traces when an API key is configured."""

import argparse
import json
import subprocess
import sys
import tempfile
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--mode", choices=("deepseek", "openai"), default="deepseek")
    args = parser.parse_args()
    output_dir = ROOT / "examples" / "model_outputs"
    trace_dir = ROOT / "examples" / "model_traces"
    output_dir.mkdir(exist_ok=True)
    trace_dir.mkdir(exist_ok=True)
    with tempfile.TemporaryDirectory() as temp:
        for case in ("conflict", "risk"):
            command = [sys.executable, "-m", "src.cli", f"examples/inputs/{case}.json",
                       "--mode", args.mode, "--db", str(Path(temp) / f"{case}.sqlite3")]
            completed = subprocess.run(command, cwd=ROOT, text=True, capture_output=True, check=False)
            if not completed.stdout:
                raise RuntimeError(f"{case}: {completed.stderr}")
            result = json.loads(completed.stdout)
            (output_dir / f"{args.mode}_{case}.json").write_text(
                json.dumps(result, ensure_ascii=False, indent=2) + "\n")
            (trace_dir / f"{args.mode}_{case}.json").write_text(
                json.dumps(result["trace"], ensure_ascii=False, indent=2) + "\n")
            print(f"{case}: {result['completion_status']} ({len(result['trace'])} steps)")
            if result["completion_status"] not in ("pending_confirmation", "blocked"):
                raise RuntimeError(f"{case}: unexpected result; inspect model output")


if __name__ == "__main__":
    main()
