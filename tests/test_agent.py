import json
import io
import os
import sqlite3
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from src.agent import run
from src.models import MockPolicy, DeepSeekModel


ROOT = Path(__file__).resolve().parents[1]


class AgentAcceptanceTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.db = Path(self.temp.name) / "drafts.sqlite3"

    def tearDown(self):
        self.temp.cleanup()

    def case(self, name, **kwargs):
        request = json.loads((ROOT / "examples" / "inputs" / f"{name}.json").read_text())
        return run(request, model=MockPolicy(), db_path=self.db, **kwargs)

    def count(self):
        with sqlite3.connect(self.db) as connection:
            return connection.execute("SELECT COUNT(*) FROM drafts").fetchone()[0]

    def test_normal_slot_saves_one_unpublished_draft(self):
        result = self.case("normal")
        self.assertEqual(result["completion_status"], "draft_ready")
        self.assertEqual(result["suggested_slot"], result["requested_slot"])
        self.assertEqual(result["draft_status"], "saved")
        self.assertFalse(result["published"])
        self.assertEqual(self.count(), 1)

    def test_missing_metadata_does_not_save(self):
        result = self.case("missing")
        self.assertEqual(result["completion_status"], "needs_input")
        self.assertIn("license", result["missing_fields"])
        self.assertEqual(self.count(), 0)

    def test_rule_risk_blocks_save(self):
        result = self.case("risk")
        self.assertEqual(result["completion_status"], "blocked")
        self.assertTrue(result["risk_reasons"])
        self.assertEqual(self.count(), 0)

    def test_conflict_proposes_alternative_and_waits_for_approval(self):
        result = self.case("conflict")
        self.assertEqual(result["completion_status"], "pending_confirmation")
        self.assertEqual(result["suggested_slot"], "2026-11-03T19:00:00+08:00")
        self.assertEqual(result["draft"]["status"], "pending_confirmation")
        self.assertTrue(result["pending_confirmation"])
        self.assertEqual([x["action"] for x in result["trace"]].count("query_slot"), 2)
        self.assertEqual(result["trace"][2]["next_action"], "query_slot")
        self.assertEqual(result["trace"][3]["next_action"], "save_draft")

    def test_duplicate_request_creates_only_one_draft(self):
        first = self.case("conflict")
        again = self.case("conflict")
        self.assertEqual(again["draft_status"], "already_exists")
        self.assertEqual(again["draft"]["request_key"], first["draft"]["request_key"])
        self.assertEqual(self.count(), 1)

    def test_exact_user_approval_updates_existing_draft_without_publishing(self):
        self.case("conflict")
        confirmed = self.case("approved_change")
        self.assertEqual(confirmed["completion_status"], "draft_ready")
        self.assertEqual(confirmed["draft"]["status"], "confirmed_time")
        self.assertFalse(confirmed["pending_confirmation"])
        self.assertFalse(confirmed["published"])
        self.assertEqual(self.count(), 1)
        repeated = self.case("conflict")
        self.assertEqual(repeated["completion_status"], "draft_ready")
        self.assertEqual(self.count(), 1)

    def test_wrong_approval_does_not_change_hard_time(self):
        self.case("conflict")
        request = json.loads((ROOT / "examples/inputs/conflict.json").read_text())
        request["approved_alternative_slot"] = "2026-11-03T20:00:00+08:00"
        result = run(request, model=MockPolicy(), db_path=self.db)
        self.assertEqual(result["completion_status"], "pending_confirmation")
        self.assertEqual(result["draft"]["status"], "pending_confirmation")
        self.assertEqual(self.count(), 1)

    def test_save_failure_is_explicit_and_not_counted_as_saved(self):
        result = self.case("normal", fail_save=True)
        self.assertEqual(result["completion_status"], "failed")
        self.assertEqual(result["draft_status"], "failed")
        self.assertEqual(result["save_error"], "simulated_storage_failure")
        self.assertEqual(self.count(), 0)

    def test_step_limit_returns_incomplete(self):
        result = self.case("normal", max_steps=2)
        self.assertEqual(result["completion_status"], "incomplete")
        self.assertEqual(result["stop_reason"], "step_limit")
        self.assertEqual(self.count(), 0)

    def test_tool_limit_returns_incomplete(self):
        result = self.case("normal", max_tools=2)
        self.assertEqual(result["completion_status"], "incomplete")
        self.assertEqual(result["stop_reason"], "tool_limit")
        self.assertEqual(self.count(), 0)

    def test_model_cannot_save_without_observed_review(self):
        class AdversarialModel:
            name = "scripted_adversary"

            def decide(self, request, evidence):
                return {"name": "save_draft", "arguments": {"slot": request["requested_slot"]}, "reason": "attempt"} if "save_draft" not in evidence else {"name": "finish", "arguments": {}, "reason": "done"}

            def observe(self, result):
                pass

        request = json.loads((ROOT / "examples/inputs/normal.json").read_text())
        result = run(request, model=AdversarialModel(), db_path=self.db)
        self.assertEqual(result["save_error"], "review_not_approved")
        self.assertEqual(self.count(), 0)

    def test_deepseek_adapter_returns_observation_to_model(self):
        responses = [
            {"choices": [{"message": {"role": "assistant", "content": None, "tool_calls": [
                {"id": "call_1", "type": "function", "function": {"name": "read_material",
                 "arguments": '{"material_id":"M01","reason":"inspect"}'}}
            ]}}]},
            {"choices": [{"message": {"role": "assistant", "content": None, "tool_calls": [
                {"id": "call_2", "type": "function", "function": {"name": "finish",
                 "arguments": '{"reason":"done"}'}}
            ]}}]},
        ]
        payloads = []

        def fake_urlopen(http_request, timeout):
            payloads.append(json.loads(http_request.data))
            return io.BytesIO(json.dumps(responses[len(payloads) - 1]).encode())

        with patch.dict(os.environ, {"DEEPSEEK_API_KEY": "test-only"}), patch("urllib.request.urlopen", side_effect=fake_urlopen):
            model = DeepSeekModel()
            first = model.decide({"material_id": "M01"}, {})
            model.observe({"found": True})
            second = model.decide({"material_id": "M01"}, {})
        self.assertEqual(first["name"], "read_material")
        self.assertEqual(second["name"], "finish")
        self.assertEqual(payloads[1]["messages"][-1]["role"], "tool")
        self.assertEqual(json.loads(payloads[1]["messages"][-1]["content"]), {"found": True})
        self.assertEqual(payloads[1]["tool_choice"], "required")
        self.assertEqual(payloads[1]["thinking"], {"type": "disabled"})

    def test_deepseek_parallel_reads_are_observed_before_next_model_call(self):
        responses = [
            {"choices": [{"message": {"role": "assistant", "content": None, "tool_calls": [
                {"id": "one", "type": "function", "function": {"name": "read_material", "arguments": '{"material_id":"M01","reason":"read"}'}},
                {"id": "two", "type": "function", "function": {"name": "check_rules", "arguments": '{"material_id":"M01","reason":"check"}'}}
            ]}}]},
            {"choices": [{"message": {"role": "assistant", "content": None, "tool_calls": [
                {"id": "three", "type": "function", "function": {"name": "finish", "arguments": '{"reason":"done"}'}}
            ]}}]},
        ]
        payloads = []

        def fake_urlopen(http_request, timeout):
            payloads.append(json.loads(http_request.data))
            return io.BytesIO(json.dumps(responses[len(payloads) - 1]).encode())

        with patch.dict(os.environ, {"DEEPSEEK_API_KEY": "test-only"}), patch("urllib.request.urlopen", side_effect=fake_urlopen):
            model = DeepSeekModel()
            self.assertEqual(model.decide({"material_id": "M01"}, {})["name"], "read_material")
            model.observe({"found": True})
            self.assertEqual(model.decide({"material_id": "M01"}, {})["name"], "check_rules")
            model.observe({"status": "approved"})
            self.assertEqual(model.decide({"material_id": "M01"}, {})["name"], "finish")
        self.assertEqual(len(payloads), 2)
        self.assertEqual([m["role"] for m in payloads[1]["messages"][-2:]], ["tool", "tool"])

    def test_deepseek_parallel_save_is_rejected_without_write(self):
        response = {"choices": [{"message": {"role": "assistant", "content": None, "tool_calls": [
            {"id": "one", "type": "function", "function": {"name": "read_material", "arguments": '{"material_id":"M04","reason":"read"}'}},
            {"id": "two", "type": "function", "function": {"name": "save_draft", "arguments": '{"slot":"2026-11-04T18:00:00+08:00","reason":"save"}'}}
        ]}}]}
        with patch.dict(os.environ, {"DEEPSEEK_API_KEY": "test-only"}), patch(
            "urllib.request.urlopen", return_value=io.BytesIO(json.dumps(response).encode())
        ):
            model = DeepSeekModel()
            request = json.loads((ROOT / "examples/inputs/normal.json").read_text())
            result = run(request, model=model, db_path=self.db, max_steps=1)
        self.assertEqual(result["trace"][0]["action"], "parallel_side_effects_rejected")
        self.assertEqual(result["completion_status"], "incomplete")
        self.assertEqual(self.count(), 0)


if __name__ == "__main__":
    unittest.main()
