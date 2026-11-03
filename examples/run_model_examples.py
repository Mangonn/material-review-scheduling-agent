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
    parser.add_argument("--cases", nargs="+", choices=("conflict", "risk", "save_failure"),
                        default=("conflict", "risk", "save_failure"))
    args = parser.parse_args()
    expected = {"conflict": "pending_confirmation", "risk": "blocked", "save_failure": "failed"}
    expected_mode = {"deepseek": "deepseek_chat", "openai": "openai_responses"}[args.mode]
    output_dir = ROOT / "examples" / "model_outputs"
    trace_dir = ROOT / "examples" / "model_traces"
    results = {}
    with tempfile.TemporaryDirectory() as temp:
        for case in args.cases:
            input_name = "normal" if case == "save_failure" else case
            command = [sys.executable, "-m", "src.cli", f"examples/inputs/{input_name}.json",
                       "--mode", args.mode, "--db", str(Path(temp) / f"{case}.sqlite3")]
            if case == "save_failure":
                command.append("--fail-save")
            completed = subprocess.run(command, cwd=ROOT, text=True, capture_output=True, check=False)
            if not completed.stdout:
                raise RuntimeError(f"{case}: {completed.stderr}")
            result = json.loads(completed.stdout)
            print(f"{case}: {result['completion_status']} ({len(result['trace'])} steps)")
            if result["completion_status"] != expected[case] or result["mode"] != expected_mode:
                print("unexpected:", case, result["stop_reason"],
                      [(item["action"], item["observation"]) for item in result["trace"]], flush=True)
                raise RuntimeError(f"{case}: unexpected result; inspect model output")
            if case == "save_failure" and (result["draft_status"] != "failed" or
                                           result["save_error"] != "simulated_storage_failure" or
                                           result["published"] or result["draft"] is not None):
                raise RuntimeError("save_failure: storage failure was misreported")
            results[case] = result
    output_dir.mkdir(exist_ok=True)
    trace_dir.mkdir(exist_ok=True)
    for case, result in results.items():
        (output_dir / f"{args.mode}_{case}.json").write_text(
            json.dumps(result, ensure_ascii=False, indent=2) + "\n")
        (trace_dir / f"{args.mode}_{case}.json").write_text(
            json.dumps(result["trace"], ensure_ascii=False, indent=2) + "\n")


if __name__ == "__main__":
    main()
