"""Real Responses API decision maker and an explicitly non-model offline policy."""

from __future__ import annotations

import json
import os
import urllib.error
import urllib.request


def _tool(name: str, description: str, properties: dict, required: list[str]) -> dict:
    properties = {**properties, "reason": {"type": "string", "description": "Brief factual basis visible in the trace; no private reasoning."}}
    return {"type": "function", "name": name, "description": description, "strict": True,
            "parameters": {"type": "object", "properties": properties,
                           "required": [*required, "reason"], "additionalProperties": False}}


TOOLS = [
    _tool("read_material", "Read source metadata for the requested material.",
          {"material_id": {"type": "string"}}, ["material_id"]),
    _tool("check_rules", "Check required metadata and synthetic review rules.",
          {"material_id": {"type": "string"}}, ["material_id"]),
    _tool("query_slot", "Check one candidate publication time and see alternatives.",
          {"slot": {"type": "string"}}, ["slot"]),
    _tool("save_draft", "Save one draft only after review and slot verification. Never publishes.",
          {"slot": {"type": "string"}}, ["slot"]),
    _tool("finish", "Stop with the current observations. Use for blocked, missing, saved, failed or impossible requests.",
          {}, []),
]


INSTRUCTIONS = """You are a material review and scheduling assistant. Select exactly one function call per turn.
First inspect the material and check rules. If metadata is missing or rule risk exists, finish without saving.
Check the requested time. When occupied, inspect an alternative time with query_slot before saving.
For a hard requested time, an alternative is only a proposal unless approved_alternative_slot exactly matches it.
You may save a proposal as pending_confirmation; never call it approved or published.
If a business tool reports failure, decide whether to inspect another option or finish. Do not claim a save succeeded unless its observation says saved=true.
Call finish when done. Put a short factual decision basis in reason. Do not reveal hidden chain of thought.
"""


class MockPolicy:
    """Deterministic observation-driven demonstration; not evidence of LLM quality."""

    name = "mock_policy"

    def decide(self, request: dict, evidence: dict) -> dict:
        mid = request["material_id"]
        if "read_material" not in evidence:
            return {"name": "read_material", "arguments": {"material_id": mid}, "reason": "需要先读取素材元数据"}
        if "check_rules" not in evidence:
            return {"name": "check_rules", "arguments": {"material_id": mid}, "reason": "根据素材检查缺失字段与规则风险"}
        review = evidence["check_rules"]
        if review["status"] != "approved":
            return {"name": "finish", "arguments": {}, "reason": "审核未通过或资料不足，不能保存草稿"}
        queried = evidence["queried_slots"]
        requested = request["requested_slot"]
        if requested not in queried:
            return {"name": "query_slot", "arguments": {"slot": requested}, "reason": "先验证用户要求的时段"}
        if "save_draft" in evidence:
            return {"name": "finish", "arguments": {}, "reason": "已观察草稿保存结果，结束本次处理"}
        if queried[requested]["available"]:
            slot = requested
        else:
            alternatives = queried[requested]["alternatives"]
            approved = request.get("approved_alternative_slot")
            ordered = ([approved] if approved else []) + [s for s in alternatives if s != approved]
            slot = next((s for s in ordered if s and (s not in queried or queried[s]["available"])), None)
            if slot is None:
                return {"name": "finish", "arguments": {}, "reason": "没有可用的替代时段"}
        if slot not in queried:
            return {"name": "query_slot", "arguments": {"slot": slot}, "reason": "原时段冲突，补查替代时段是否可用"}
        if not queried[slot]["available"]:
            return {"name": "finish", "arguments": {}, "reason": "候选时段不可用"}
        return {"name": "save_draft", "arguments": {"slot": slot}, "reason": "审核通过且时段可用，仅保存草稿"}

    def observe(self, result: dict) -> None:
        pass


class OpenAIModel:
    """A real model selects each function; tools execute locally in the runner."""

    name = "openai_responses"

    def __init__(self):
        self.api_key = os.getenv("OPENAI_API_KEY")
        if not self.api_key:
            raise ValueError("OPENAI_API_KEY is required for --mode openai")
        self.model = os.getenv("OPENAI_MODEL", "gpt-6.1-sol")
        self.response_id = None
        self.pending_output = None
        self.turn = 0

    def decide(self, request: dict, evidence: dict) -> dict:
        payload = {
            "model": self.model, "instructions": INSTRUCTIONS, "tools": TOOLS,
            "tool_choice": "required", "parallel_tool_calls": False, "store": True,
            "max_output_tokens": 1200,
            "input": ([self.pending_output] if self.pending_output else [
                {"role": "user", "content": json.dumps(request, ensure_ascii=False)}]),
        }
        if self.response_id:
            payload["previous_response_id"] = self.response_id
        body = json.dumps(payload, ensure_ascii=False).encode()
        http_request = urllib.request.Request(
            "https://api.openai.com/v1/responses", data=body,
            headers={"Authorization": f"Bearer {self.api_key}", "Content-Type": "application/json"},
        )
        try:
            with urllib.request.urlopen(http_request, timeout=45) as response:
                data = json.load(response)
        except urllib.error.HTTPError as exc:
            raise RuntimeError(f"model_http_{exc.code}") from exc
        except (urllib.error.URLError, TimeoutError) as exc:
            raise RuntimeError(f"model_transport_error:{type(exc).__name__}") from exc
        self.response_id = data["id"]
        self.turn += 1
        calls = [item for item in data.get("output", []) if item.get("type") == "function_call"]
        if len(calls) > 1:
            raise RuntimeError("model_returned_parallel_calls")
        if not calls:
            text = " ".join(part.get("text", "") for item in data.get("output", [])
                            for part in item.get("content", []) if part.get("type") == "output_text")
            return {"name": "finish", "arguments": {}, "reason": text[:200] or "模型结束",
                    "model_turn": self.turn}
        call = calls[0]
        self.call_id = call["call_id"]
        try:
            args = json.loads(call["arguments"])
        except json.JSONDecodeError as exc:
            raise RuntimeError("invalid_model_tool_arguments") from exc
        return {"name": call["name"], "arguments": args,
                "reason": str(args.get("reason", "模型选择此动作"))[:200], "model_turn": self.turn}

    def observe(self, result: dict) -> None:
        self.pending_output = {"type": "function_call_output", "call_id": self.call_id,
                               "output": json.dumps(result, ensure_ascii=False)}


class DeepSeekModel:
    """DeepSeek Chat Completions with model-selected local function calls."""

    name = "deepseek_chat"

    def __init__(self):
        self.api_key = os.getenv("DEEPSEEK_API_KEY")
        if not self.api_key:
            raise ValueError("DEEPSEEK_API_KEY is required for --mode deepseek")
        self.model = os.getenv("DEEPSEEK_MODEL", "deepseek-flash")
        self.messages = None
        self.pending_calls = []
        self.rejected_call_ids = []
        self.turn = 0

    def _next_call(self) -> dict:
        call = self.pending_calls.pop(0)
        self.call_id = call["id"]
        try:
            args = json.loads(call["function"]["arguments"])
        except json.JSONDecodeError as exc:
            raise RuntimeError("invalid_model_tool_arguments") from exc
        return {"name": call["function"]["name"], "arguments": args,
                "reason": str(args.get("reason", "模型选择此动作"))[:200], "model_turn": self.turn}

    def decide(self, request: dict, evidence: dict) -> dict:
        if self.pending_calls:
            return self._next_call()
        if self.messages is None:
            self.messages = [
                {"role": "system", "content": INSTRUCTIONS},
                {"role": "user", "content": json.dumps(request, ensure_ascii=False)},
            ]
        functions = [{"type": "function", "function": {
            "name": tool["name"], "description": tool["description"],
            "parameters": tool["parameters"],
        }} for tool in TOOLS]
        payload = {"model": self.model, "messages": self.messages, "tools": functions,
                   "tool_choice": "required", "thinking": {"type": "disabled"},
                   "max_tokens": 1000}
        http_request = urllib.request.Request(
            "https://api.deepseek.com/chat/completions",
            data=json.dumps(payload, ensure_ascii=False).encode(),
            headers={"Authorization": f"Bearer {self.api_key}", "Content-Type": "application/json"},
        )
        try:
            with urllib.request.urlopen(http_request, timeout=45) as response:
                data = json.load(response)
        except urllib.error.HTTPError as exc:
            raise RuntimeError(f"model_http_{exc.code}") from exc
        except (urllib.error.URLError, TimeoutError) as exc:
            raise RuntimeError(f"model_transport_error:{type(exc).__name__}") from exc
        choice = data["choices"][0]
        self.turn += 1
        message = choice["message"]
        calls = message.get("tool_calls") or []
        if not calls:
            raise RuntimeError("model_returned_no_tool_call")
        self.messages.append({"role": "assistant", "content": message.get("content"), "tool_calls": calls})
        if len(calls) > 1 and any(
            call["function"]["name"] not in ("read_material", "check_rules", "query_slot")
            for call in calls
        ):
            self.rejected_call_ids = [call["id"] for call in calls]
            return {"name": "parallel_side_effects_rejected", "arguments": {},
                    "reason": "模型并行请求包含写入或结束动作，要求单独重选", "model_turn": self.turn}
        self.pending_calls = list(calls)
        return self._next_call()

    def observe(self, result: dict) -> None:
        if self.rejected_call_ids:
            for call_id in self.rejected_call_ids:
                self.messages.append({"role": "tool", "tool_call_id": call_id,
                                      "content": json.dumps({"error": "parallel_side_effects_rejected"})})
            self.rejected_call_ids = []
            return
        self.messages.append({"role": "tool", "tool_call_id": self.call_id,
                              "content": json.dumps(result, ensure_ascii=False)})
