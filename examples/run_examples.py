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
               "--db", str(db)]
    if fail_save:
        command.append("--fail-save")
    completed = subprocess.run(command, cwd=ROOT, capture_output=True, text=True, check=False)
    if completed.returncode not in (0, 2) or not completed.stdout:
        raise RuntimeError(f"example {name} failed: {completed.stderr}")
    return json.loads(completed.stdout)


def save(name: str, result: dict):
    OUTPUTS.mkdir(exist_ok=True)
    TRACES.mkdir(exist_ok=True)
    (OUTPUTS / f"{name}.json").write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n")
    (TRACES / f"{name}.json").write_text(json.dumps(result["trace"], ensure_ascii=False, indent=2) + "\n")


with tempfile.TemporaryDirectory() as directory:
    base = Path(directory)
    for name in ("normal", "missing", "risk"):
        save(name, invoke(name, base / f"{name}.sqlite3"))
    conflict_db = base / "conflict.sqlite3"
    save("conflict", invoke("conflict", conflict_db))
    save("duplicate", invoke("conflict", conflict_db))
    save("approved_change", invoke("approved_change", conflict_db))
    save("save_failure", invoke("normal", base / "failure.sqlite3", fail_save=True))
print("Generated 7 CLI outputs and 7 traces in examples/")
