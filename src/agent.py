"""Bounded observe-decide-act loop. Business writes are guarded outside the model."""

from __future__ import annotations

from pathlib import Path

from .business import BusinessTools, canonical_key, validate_request


def _result(request: dict, evidence: dict, trace: list, mode: str, stop_reason: str | None) -> dict:
    review = evidence.get("check_rules", {})
    saved = evidence.get("save_draft")
    existing = evidence.get("existing_draft")
    draft = (saved or {}).get("draft") or existing
    proposed = draft["proposed_slot"] if draft else evidence.get("proposed_slot")
    pending = []
    if review.get("missing_fields"):
        pending.append("补齐素材字段：" + ", ".join(review["missing_fields"]))
    if review.get("risks"):
        pending.append("处理审核风险后重新提交")
    if proposed and request["requirement"] == "hard" and proposed != request["requested_slot"]:
        if request.get("approved_alternative_slot") != proposed and (not draft or draft["status"] == "pending_confirmation"):
            pending.append(f"确认将硬性时段 {request['requested_slot']} 改为 {proposed}")
    if existing:
        draft_status = "already_exists"
    elif saved and saved.get("saved"):
        draft_status = "already_exists" if saved.get("duplicate") else "saved"
    elif saved:
        draft_status = "failed"
    else:
        draft_status = "not_attempted"
    if stop_reason:
        completion = "incomplete"
    elif review.get("status") == "needs_information" or review.get("status") == "missing_material":
        completion = "needs_input"
    elif review.get("status") == "blocked":
        completion = "blocked"
    elif saved and not saved.get("saved"):
        completion = "failed"
    elif draft:
        completion = "pending_confirmation" if draft["status"] == "pending_confirmation" else "draft_ready"
    else:
        completion = "incomplete"
    return {
        "material_id": request["material_id"], "requested_slot": request["requested_slot"],
        "requirement": request["requirement"], "review_status": review.get("status", "unreviewed"),
        "risk_reasons": review.get("risks", []), "missing_fields": review.get("missing_fields", []),
        "suggested_slot": proposed, "pending_confirmation": pending,
        "draft_status": draft_status, "draft": draft,
        "save_error": (saved or {}).get("error"), "completion_status": completion,
        "stop_reason": stop_reason, "mode": mode, "published": False, "trace": trace,
    }


def run(request: dict, *, model, db_path: Path, fail_save: bool = False,
        max_steps: int = 10, max_tools: int = 8, data_dir: Path | None = None) -> dict:
    validate_request(request)
    if max_steps < 1 or max_tools < 1:
        raise ValueError("max_steps and max_tools must be positive")
    tools = BusinessTools(db_path, fail_save=fail_save, data_dir=data_dir)
    evidence: dict = {"queried_slots": {}}
    trace: list = []
    key = canonical_key(request)
    try:
        existing = tools.existing(key)
        if existing:
            approved = request.get("approved_alternative_slot")
            if approved and existing["status"] == "pending_confirmation":
                existing = tools.confirm_existing(key, approved)
                trace.append({"step": 0, "actor": "system", "action": "apply_user_confirmation",
                              "arguments": {"approved_alternative_slot": approved},
                              "observation": {"status": existing["status"]},
                              "decision_basis": "仅接受与已有建议时段完全相同的用户确认"})
            evidence["existing_draft"] = existing
            evidence["check_rules"] = tools.check_rules(request["material_id"])
            trace.append({"step": 0, "actor": "system", "action": "idempotency_lookup",
                          "arguments": {"request_key": key}, "observation": {"found": True, "draft": existing},
                          "decision_basis": "相同请求已保存，直接返回原草稿"})
            return _result(request, evidence, trace, model.name, None)
        tool_count = 0
        for step in range(1, max_steps + 1):
            try:
                decision = model.decide(request, evidence)
            except Exception as exc:
                trace.append({"step": step, "actor": model.name, "action": "error",
                              "observation": str(exc), "decision_basis": "模型调用失败"})
                return _result(request, evidence, trace, model.name, "model_error")
            name = decision.get("name")
            args = decision.get("arguments", {})
            reason = decision.get("reason", "")
            if not isinstance(args, dict):
                return _result(request, evidence, trace, model.name, "invalid_model_arguments")
            if name == "finish":
                entry = {"step": step, "actor": model.name, "action": "finish",
                         "arguments": {}, "observation": "stopped", "decision_basis": reason}
                if "model_turn" in decision:
                    entry["model_turn"] = decision["model_turn"]
                trace.append(entry)
                return _result(request, evidence, trace, model.name, None)
            if tool_count >= max_tools:
                trace.append({"step": step, "actor": "system", "action": "tool_limit",
                              "arguments": {}, "observation": "not executed", "decision_basis": "达到工具调用上限"})
                return _result(request, evidence, trace, model.name, "tool_limit")
            tool_count += 1
            if name in ("read_material", "check_rules") and args.get("material_id") != request["material_id"]:
                observation = {"error": "material_id_mismatch"}
            elif name == "read_material":
                observation = tools.read_material(request["material_id"])
                evidence[name] = observation
            elif name == "check_rules":
                observation = tools.check_rules(request["material_id"])
                evidence[name] = observation
            elif name == "query_slot" and isinstance(args.get("slot"), str):
                observation = tools.query_slot(args["slot"])
                evidence["queried_slots"][args["slot"]] = observation
                if observation["available"]:
                    evidence["proposed_slot"] = args["slot"]
            elif name == "save_draft" and isinstance(args.get("slot"), str):
                observation = tools.save_draft(request, args["slot"], evidence)
                evidence[name] = observation
                if observation.get("saved"):
                    evidence["proposed_slot"] = args["slot"]
            else:
                observation = {"error": "unknown_tool_or_invalid_arguments"}
            entry = {"step": step, "actor": model.name, "action": name,
                     "arguments": {k: v for k, v in args.items() if k != "reason"},
                     "observation": observation, "decision_basis": reason}
            if "model_turn" in decision:
                entry["model_turn"] = decision["model_turn"]
            trace.append(entry)
            model.observe(observation)
        return _result(request, evidence, trace, model.name, "step_limit")
    finally:
        tools.close()
