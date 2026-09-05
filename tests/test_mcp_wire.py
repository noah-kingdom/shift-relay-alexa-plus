from pathlib import Path
import json
import tempfile

from fastapi.testclient import TestClient

import shift_relay.mcp_wire as wire
from shift_relay.core import DemoActionExecutor, DemoVerifier, ShiftStore


def rpc(client: TestClient, req_id: int, method: str, params=None):
    response = client.post(
        "/mcp",
        headers={"Accept": "application/json, text/event-stream", "MCP-Protocol-Version": "2025-11-25"},
        json={"jsonrpc": "2.0", "id": req_id, "method": method, "params": params or {}},
    )
    assert response.status_code == 200
    return response.json()["result"]


def call(client: TestClient, req_id: int, name: str, arguments: dict):
    return rpc(client, req_id, "tools/call", {"name": name, "arguments": arguments})


def payload(call_result: dict):
    """Normalize compatibility-harness and official-FastMCP-style tool results.

    The harness may expose structuredContent while official FastMCP v1 commonly
    serializes dict results into content[0].text. Semantics are what this suite
    protects; official SDK envelope behavior is tested separately.
    """
    if call_result.get("structuredContent") is not None:
        return call_result["structuredContent"]
    content = call_result.get("content") or []
    if content and isinstance(content[0], dict) and content[0].get("text"):
        try:
            return json.loads(content[0]["text"])
        except Exception:
            return {"text": content[0]["text"]}
    return call_result


def test_mcp_streamable_http_wire_round_trip_end_to_end():
    with tempfile.TemporaryDirectory() as td:
        wire.store = ShiftStore(Path(td) / "wire.db")
        wire.verifier = DemoVerifier()
        wire.executor = DemoActionExecutor()
        client = TestClient(wire.app)

        init = rpc(client, 1, "initialize", {"protocolVersion": "2025-11-25", "capabilities": {}, "clientInfo": {"name": "wire-test", "version": "1"}})
        assert init["protocolVersion"] == "2025-11-25"
        tools = rpc(client, 2, "tools/list")
        names = {x["name"] for x in tools["tools"]}
        assert {"start_shift", "report_exception", "verify_open_loop", "prepare_action", "approve_action", "execute_approved_action", "confirm_action_result"}.issubset(names)

        shift = payload(call(client, 3, "start_shift", {"site_id": "qsr-17", "worker_id": "alex", "shift_type": "closing"}))
        sid = shift["shift_id"]
        delivery = payload(call(client, 4, "report_exception", {
            "site_id": "qsr-17", "shift_id": sid, "created_by": "alex",
            "summary": "The chilled-goods truck seems to have missed its drop.",
            "category": "delivery", "subject_key": "freezer_delivery", "risk": "high", "priority": "high",
        }))
        cups = payload(call(client, 5, "report_exception", {
            "site_id": "qsr-17", "shift_id": sid, "created_by": "alex",
            "summary": "We have barely any 20-ounce cups left for the morning rush.",
            "category": "inventory", "subject_key": "large_cups", "risk": "high", "priority": "urgent",
        }))

        dv = payload(call(client, 6, "verify_open_loop", {"loop_id": delivery["id"]}))
        cv = payload(call(client, 7, "verify_open_loop", {"loop_id": cups["id"]}))
        assert dv["verification"]["outcome"] == "inconclusive"
        assert cv["verification"]["outcome"] == "verified"

        blocked = call(client, 8, "prepare_action", {"loop_id": delivery["id"], "action_type": "supplier_followup", "payload": {}, "risk": "high"})
        assert blocked["isError"] is True
        assert payload(blocked)["blocked"] is True

        prepared = payload(call(client, 9, "prepare_action", {"loop_id": cups["id"], "action_type": "restock_request", "payload": {"sku": "LARGE-CUP", "quantity_cases": 10}, "risk": "high"}))
        approved = payload(call(client, 10, "approve_action", {"action_id": prepared["id"], "approved_by": "jamie"}))
        assert approved["status"] == "approved"
        executed = payload(call(client, 11, "execute_approved_action", {"action_id": prepared["id"]}))
        assert executed["status"] == "executed"
        confirmed = payload(call(client, 12, "confirm_action_result", {"action_id": prepared["id"]}))
        assert confirmed["status"] == "confirmed"

        # Evidence arrives later: the same previously-blocked delivery claim changes state.
        wire.verifier.inject_delivery_exception("missed_delivery")
        flipped = payload(call(client, 13, "verify_open_loop", {"loop_id": delivery["id"]}))
        assert flipped["verification"]["outcome"] == "verified"
        delivery_action = payload(call(client, 14, "prepare_action", {"loop_id": delivery["id"], "action_type": "supplier_followup", "payload": {"supplier": "FreezerCo"}, "risk": "high"}))
        call(client, 15, "approve_action", {"action_id": delivery_action["id"], "approved_by": "jamie"})
        call(client, 16, "execute_approved_action", {"action_id": delivery_action["id"]})
        closed = payload(call(client, 17, "confirm_action_result", {"action_id": delivery_action["id"]}))
        assert closed["status"] == "confirmed"
