"""Execute the CLI to regenerate committed outputs and traces from synthetic data."""

import json
import subprocess
import sys
import tempfile
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
OUTPUTS = ROOT / "examples" / "outputs"
TRACES = ROOT / "examples" / "traces"


def invoke(name: str, db: Path, *, fail_save: bool = False):
    command = [sys.executable, "-m", "src.cli", str(ROOT / "examples/inputs" / f"{name}.json"),
               "--mode", "mock", "--db", str(db)]
    if fail_save:
        command.append("--fail-save")
    completed = subprocess.run(command, cwd=ROOT, capture_output=True, text=True, check=False)
    if completed.returncode not in (0, 2) or not completed.stdout:
        raise RuntimeError(f"example {name} failed: {completed.stderr}")
    return json.loads(completed.stdout)


EXPECTED = {
    "normal": "draft_ready", "missing": "needs_input", "risk": "blocked",
    "conflict": "pending_confirmation", "duplicate": "pending_confirmation",
    "approved_change": "draft_ready", "save_failure": "failed",
}


def check(name: str, result: dict):
    if result["mode"] != "mock_policy" or result["completion_status"] != EXPECTED[name]:
        raise RuntimeError(f"{name}: unexpected offline result; inspect CLI output")
    return result


results = {}
with tempfile.TemporaryDirectory() as directory:
    base = Path(directory)
    for name in ("normal", "missing", "risk"):
        results[name] = check(name, invoke(name, base / f"{name}.sqlite3"))
    conflict_db = base / "conflict.sqlite3"
    results["conflict"] = check("conflict", invoke("conflict", conflict_db))
    results["duplicate"] = check("duplicate", invoke("conflict", conflict_db))
    results["approved_change"] = check("approved_change", invoke("approved_change", conflict_db))
    results["save_failure"] = check("save_failure", invoke("normal", base / "failure.sqlite3", fail_save=True))
OUTPUTS.mkdir(exist_ok=True)
TRACES.mkdir(exist_ok=True)
for name, result in results.items():
    (OUTPUTS / f"{name}.json").write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n")
    (TRACES / f"{name}.json").write_text(json.dumps(result["trace"], ensure_ascii=False, indent=2) + "\n")
print("Generated 7 CLI outputs and 7 traces in examples/")
