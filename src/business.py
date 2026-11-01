"""Small, deterministic business tools and non-negotiable write guards."""

from __future__ import annotations

import hashlib
import json
import sqlite3
from datetime import datetime
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def canonical_key(request: dict) -> str:
    fields = {key: request.get(key) for key in (
        "material_id", "requested_slot", "requirement"
    )}
    return hashlib.sha256(json.dumps(fields, sort_keys=True, ensure_ascii=False).encode()).hexdigest()


def validate_request(request: dict) -> None:
    if not isinstance(request, dict):
        raise ValueError("Input must be a JSON object")
    if not isinstance(request.get("material_id"), str) or not request["material_id"].strip():
        raise ValueError("material_id is required")
    if request.get("requirement") not in ("hard", "soft"):
        raise ValueError("requirement must be hard or soft")
    for field in ("requested_slot", "approved_alternative_slot"):
        value = request.get(field)
        if field == "approved_alternative_slot" and value is None:
            continue
        if not isinstance(value, str):
            raise ValueError(f"{field} must be an ISO 8601 timestamp")
        try:
            parsed = datetime.fromisoformat(value)
        except ValueError as exc:
            raise ValueError(f"{field} must be an ISO 8601 timestamp") from exc
        if parsed.tzinfo is None:
            raise ValueError(f"{field} needs a timezone offset")


class BusinessTools:
    def __init__(self, db_path: Path, *, fail_save: bool = False, data_dir: Path | None = None):
        self.data_dir = data_dir or ROOT / "data"
        self.materials = json.loads((self.data_dir / "materials.json").read_text())
        self.schedule = json.loads((self.data_dir / "schedule.json").read_text())
        self.rules = json.loads((self.data_dir / "rules.json").read_text())
        self.fail_save = fail_save
        self.db = sqlite3.connect(db_path)
        self.db.execute("""CREATE TABLE IF NOT EXISTS drafts (
            request_key TEXT PRIMARY KEY, material_id TEXT NOT NULL,
            requested_slot TEXT NOT NULL, proposed_slot TEXT NOT NULL,
            status TEXT NOT NULL, created_at TEXT NOT NULL
        )""")
        self.db.commit()

    def close(self) -> None:
        self.db.close()

    def existing(self, key: str) -> dict | None:
        row = self.db.execute(
            "SELECT request_key, material_id, requested_slot, proposed_slot, status FROM drafts WHERE request_key=?",
            (key,),
        ).fetchone()
        return dict(zip(("request_key", "material_id", "requested_slot", "proposed_slot", "status"), row)) if row else None

    def confirm_existing(self, key: str, approved_slot: str) -> dict | None:
        """An explicit user approval changes draft status, never publishes."""
        existing = self.existing(key)
        if not existing or existing["status"] != "pending_confirmation":
            return existing
        if existing["proposed_slot"] != approved_slot:
            return existing
        self.db.execute("UPDATE drafts SET status='confirmed_time' WHERE request_key=?", (key,))
        self.db.commit()
        return self.existing(key)

    def read_material(self, material_id: str) -> dict:
        item = self.materials.get(material_id)
        return {"found": bool(item), "material_id": material_id, "material": item}

    def check_rules(self, material_id: str) -> dict:
        item = self.materials.get(material_id)
        if item is None:
            return {"status": "missing_material", "missing_fields": ["material"], "risks": []}
        missing = [field for field in self.rules["required_fields"] if not item.get(field)]
        risks = []
        if item.get("rights") and item["rights"] not in self.rules["allowed_rights"]:
            risks.append("素材权属值不受支持")
        for claim in self.rules["prohibited_claims"]:
            if claim in item.get("caption", ""):
                risks.append(f"文案命中禁用声明：{claim}")
        status = "needs_information" if missing else "blocked" if risks else "approved"
        return {"status": status, "missing_fields": missing, "risks": risks}

    def query_slot(self, slot: str) -> dict:
        if slot not in self.schedule["candidate_slots"]:
            return {"slot": slot, "available": False, "reason": "not_a_candidate", "alternatives": []}
        existing = next((x for x in self.schedule["occupied"] if x["slot"] == slot), None)
        draft = self.db.execute("SELECT material_id FROM drafts WHERE proposed_slot=?", (slot,)).fetchone()
        occupied_by = existing["material_id"] if existing else draft[0] if draft else None
        alternatives = [s for s in self.schedule["candidate_slots"] if s != slot and not self._occupied(s)]
        return {"slot": slot, "available": occupied_by is None,
                "reason": "occupied" if occupied_by else "free", "occupied_by": occupied_by,
                "alternatives": alternatives}

    def _occupied(self, slot: str) -> bool:
        return any(x["slot"] == slot for x in self.schedule["occupied"]) or bool(
            self.db.execute("SELECT 1 FROM drafts WHERE proposed_slot=?", (slot,)).fetchone()
        )

    def save_draft(self, request: dict, slot: str, evidence: dict) -> dict:
        # Never trust the model's claim that review or availability has passed.
        material = evidence.get("read_material")
        rules = evidence.get("check_rules")
        checked = evidence.get("queried_slots", {}).get(slot)
        if not material or not material["found"] or not rules or rules["status"] != "approved":
            return {"saved": False, "error": "review_not_approved"}
        if not checked or not checked["available"]:
            return {"saved": False, "error": "slot_not_verified_available"}
        if self.fail_save:
            return {"saved": False, "error": "simulated_storage_failure"}
        key = canonical_key(request)
        existing = self.existing(key)
        if existing:
            return {"saved": True, "duplicate": True, "draft": existing}
        # Recheck within the write transaction so a stale model observation cannot cause overlap.
        status = "pending_confirmation" if (
            request["requirement"] == "hard" and slot != request["requested_slot"]
            and request.get("approved_alternative_slot") != slot
        ) else "ready_for_confirmation"
        try:
            self.db.execute("BEGIN IMMEDIATE")
            if self._occupied(slot):
                self.db.rollback()
                return {"saved": False, "error": "slot_became_occupied"}
            self.db.execute(
                "INSERT INTO drafts VALUES (?, ?, ?, ?, ?, ?)",
                (key, request["material_id"], request["requested_slot"], slot, status,
                 datetime.now().astimezone().isoformat(timespec="seconds")),
            )
            self.db.commit()
        except sqlite3.Error as exc:
            self.db.rollback()
            return {"saved": False, "error": f"storage_error:{type(exc).__name__}"}
        return {"saved": True, "duplicate": False, "draft": self.existing(key)}
