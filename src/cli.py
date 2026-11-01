"""CLI entry point. Run as python -m src.cli from the project root."""

from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

from .agent import run
from .models import MockPolicy, OpenAIModel, DeepSeekModel


def load_local_env() -> None:
    """Read only documented keys from .env; never execute shell content."""
    path = Path(".env")
    if not path.exists():
        return
    allowed = {"OPENAI_API_KEY", "OPENAI_MODEL", "DEEPSEEK_API_KEY", "DEEPSEEK_MODEL"}
    for line in path.read_text(encoding="utf-8").splitlines():
        if not line.strip() or line.lstrip().startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        key = key.strip()
        if key in allowed:
            os.environ.setdefault(key, value.strip().strip("'\""))


def main() -> int:
    parser = argparse.ArgumentParser(description="Review a material and save a publication draft")
    parser.add_argument("input", type=Path, help="Request JSON file")
    parser.add_argument("--mode", choices=("mock", "openai", "deepseek"), default="mock")
    parser.add_argument("--db", type=Path, default=Path("work/drafts.sqlite3"))
    parser.add_argument("--output", type=Path)
    parser.add_argument("--fail-save", action="store_true", help="Inject a synthetic save failure")
    parser.add_argument("--max-steps", type=int, default=10)
    parser.add_argument("--max-tools", type=int, default=8)
    args = parser.parse_args()
    try:
        request = json.loads(args.input.read_text(encoding="utf-8"))
        load_local_env()
        model = {"mock": MockPolicy, "openai": OpenAIModel, "deepseek": DeepSeekModel}[args.mode]()
        args.db.parent.mkdir(parents=True, exist_ok=True)
        result = run(request, model=model, db_path=args.db, fail_save=args.fail_save,
                     max_steps=args.max_steps, max_tools=args.max_tools)
        content = json.dumps(result, ensure_ascii=False, indent=2) + "\n"
        if args.output:
            args.output.parent.mkdir(parents=True, exist_ok=True)
            args.output.write_text(content, encoding="utf-8")
        else:
            print(content, end="")
        return 0 if result["completion_status"] in ("draft_ready", "pending_confirmation", "blocked", "needs_input") else 2
    except (ValueError, OSError, json.JSONDecodeError) as exc:
        print(json.dumps({"error": str(exc), "completion_status": "invalid_input"}, ensure_ascii=False), file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
