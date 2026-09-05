"""SDK-independent MCP Streamable HTTP compatibility harness.

Purpose:
- Prove the SHIFT//RELAY tool surface can complete MCP JSON-RPC wire round-trips
  even in environments where the official ``mcp`` Python package is unavailable.
- Keep the official FastMCP adapter (``mcp_server.py``) as the submission adapter.

This module intentionally implements only the MCP methods required for local
compatibility testing: initialize, notifications/initialized, ping, tools/list,
and tools/call. Final submission certification should still be performed with
Amazon's accepted Alexa+ path and/or MCP Inspector using the official SDK.
"""
from __future__ import annotations

from dataclasses import asdict
import json
import os
from pathlib import Path
from typing import Any, Callable

from fastapi import FastAPI, Header, Request
from fastapi.responses import JSONResponse, Response

from .core import DemoActionExecutor, DemoVerifier, Priority, RiskLevel, ShiftStore, summarize_handoff

PROTOCOL_VERSION = "2025-11-25"
DB_PATH = os.getenv("SHIFT_RELAY_WIRE_DB", "shiftrelay-wire.db")
store = ShiftStore(Path(DB_PATH))
verifier = DemoVerifier()
executor = DemoActionExecutor()

app = FastAPI(title="SHIFT//RELAY MCP Wire Harness", version="0.3.0")


def _schema(properties: dict[str, Any], required: list[str]) -> dict[str, Any]:
    return {"type": "object", "properties": properties, "required": required, "additionalProperties": False}


TOOLS: list[dict[str, Any]] = [
    {"name": "start_shift", "description": "Start a frontline shift and return a durable shift id.",
     "inputSchema": _schema({"site_id": {"type": "string"}, "worker_id": {"type": "string"}, "shift_type": {"type": "string"}}, ["site_id", "worker_id", "shift_type"])},
    {"name": "report_exception", "description": "Create one operational loop. Call once per distinct issue extracted from a user utterance.",
     "inputSchema": _schema({
         "site_id": {"type": "string"}, "shift_id": {"type": "string"}, "created_by": {"type": "string"},
         "summary": {"type": "string"}, "category": {"type": "string"}, "subject_key": {"type": "string"},
         "risk": {"type": "string", "enum": ["low", "high"], "default": "low"},
         "priority": {"type": "string", "enum": ["low", "medium", "high", "urgent"], "default": "medium"},
         "owner": {"type": ["string", "null"]}, "due": {"type": ["string", "null"]}, "next_action": {"type": ["string", "null"]},
     }, ["site_id", "shift_id", "created_by", "summary", "category", "subject_key"])},
    {"name": "verify_open_loop", "description": "Check evidence sources without upgrading inconclusive reports to facts.",
     "inputSchema": _schema({"loop_id": {"type": "string"}}, ["loop_id"])},
    {"name": "pursue_open_loops", "description": "Re-check unresolved, unverified loops using available evidence sources.",
     "inputSchema": _schema({"site_id": {"type": "string"}}, ["site_id"])},
    {"name": "get_open_loops", "description": "Return unresolved operational work independent of session/worker.",
     "inputSchema": _schema({"site_id": {"type": "string"}}, ["site_id"])},
    {"name": "close_shift", "description": "Close a shift while unresolved operational loops remain durable.",
     "inputSchema": _schema({"shift_id": {"type": "string"}}, ["shift_id"])},
    {"name": "resume_shift", "description": "Start a new shift and surface carried-over unresolved work.",
     "inputSchema": _schema({"site_id": {"type": "string"}, "worker_id": {"type": "string"}, "shift_type": {"type": "string"}}, ["site_id", "worker_id", "shift_type"])},
    {"name": "prepare_action", "description": "Prepare an action; high-risk actions fail closed on unverified state.",
     "inputSchema": _schema({"loop_id": {"type": "string"}, "action_type": {"type": "string"}, "payload": {"type": "object"}, "risk": {"type": "string", "enum": ["low", "high"], "default": "high"}}, ["loop_id", "action_type", "payload"])},
    {"name": "approve_action", "description": "Record explicit human approval for a prepared action.",
     "inputSchema": _schema({"action_id": {"type": "string"}, "approved_by": {"type": "string"}}, ["action_id", "approved_by"])},
    {"name": "execute_approved_action", "description": "Execute an action only after required approval.",
     "inputSchema": _schema({"action_id": {"type": "string"}}, ["action_id"])},
    {"name": "confirm_action_result", "description": "Confirm external execution and close the operational loop.",
     "inputSchema": _schema({"action_id": {"type": "string"}}, ["action_id"])},
]


def _call_tool(name: str, args: dict[str, Any]) -> Any:
    if name == "start_shift":
        return store.start_shift(args["site_id"], args["worker_id"], args["shift_type"])
    if name == "report_exception":
        item = store.report_exception(
            site_id=args["site_id"], shift_id=args["shift_id"], created_by=args["created_by"],
            summary=args["summary"], category=args["category"], subject_key=args["subject_key"],
            risk=RiskLevel(args.get("risk", "low")), priority=Priority(args.get("priority", "medium")),
            owner=args.get("owner"), due=args.get("due"), next_action=args.get("next_action"),
        )
        return asdict(item)
    if name == "verify_open_loop":
        loop, result = store.verify_loop(args["loop_id"], verifier)
        return {"loop": asdict(loop), "verification": asdict(result)}
    if name == "pursue_open_loops":
        return {"results": store.pursue_open_loops(args["site_id"], verifier)}
    if name == "get_open_loops":
        loops = store.get_open_loops(args["site_id"])
        return {"open_loops": [asdict(x) for x in loops], "spoken_handoff": summarize_handoff(loops)}
    if name == "close_shift":
        return store.close_shift(args["shift_id"])
    if name == "resume_shift":
        result = store.resume_shift(args["site_id"], args["worker_id"], args["shift_type"])
        result["spoken_handoff"] = summarize_handoff(store.get_open_loops(args["site_id"]))
        return result
    if name == "prepare_action":
        return asdict(store.prepare_action(loop_id=args["loop_id"], action_type=args["action_type"], payload=args["payload"], risk=RiskLevel(args.get("risk", "high"))))
    if name == "approve_action":
        return asdict(store.approve_action(args["action_id"], args["approved_by"]))
    if name == "execute_approved_action":
        return asdict(store.execute_action(args["action_id"], executor))
    if name == "confirm_action_result":
        return asdict(store.confirm_action(args["action_id"], executor))
    raise KeyError(f"Unknown tool: {name}")


def _result(req_id: Any, result: Any) -> JSONResponse:
    return JSONResponse({"jsonrpc": "2.0", "id": req_id, "result": result}, headers={"MCP-Protocol-Version": PROTOCOL_VERSION})


def _error(req_id: Any, code: int, message: str, data: Any = None) -> JSONResponse:
    err: dict[str, Any] = {"code": code, "message": message}
    if data is not None:
        err["data"] = data
    return JSONResponse({"jsonrpc": "2.0", "id": req_id, "error": err}, status_code=200, headers={"MCP-Protocol-Version": PROTOCOL_VERSION})


@app.post("/mcp")
async def mcp_endpoint(request: Request, mcp_protocol_version: str | None = Header(default=None)) -> Response:
    try:
        body = await request.json()
    except Exception:
        return _error(None, -32700, "Parse error")
    if not isinstance(body, dict) or body.get("jsonrpc") != "2.0":
        return _error(body.get("id") if isinstance(body, dict) else None, -32600, "Invalid Request")

    method = body.get("method")
    req_id = body.get("id")
    params = body.get("params") or {}

    # Notifications have no id and receive an empty 202 response.
    if method == "notifications/initialized" and "id" not in body:
        return Response(status_code=202, headers={"MCP-Protocol-Version": PROTOCOL_VERSION})

    if method == "initialize":
        client_version = params.get("protocolVersion")
        return _result(req_id, {
            "protocolVersion": PROTOCOL_VERSION if client_version != PROTOCOL_VERSION else client_version,
            "capabilities": {"tools": {"listChanged": False}},
            "serverInfo": {"name": "SHIFT//RELAY", "version": "0.3.0"},
            "instructions": (
                "Maintain trusted operational state across shifts. Human reports are not verified facts. "
                "Verify before high-risk actions, require explicit approval, and confirm external results."
            ),
        })
    if method == "ping":
        return _result(req_id, {})
    if method == "tools/list":
        return _result(req_id, {"tools": TOOLS})
    if method == "tools/call":
        name = params.get("name")
        args = params.get("arguments") or {}
        try:
            output = _call_tool(name, args)
            payload = json.dumps(output, sort_keys=True, default=str)
            return _result(req_id, {
                "content": [{"type": "text", "text": payload}],
                "structuredContent": output,
                "isError": False,
            })
        except PermissionError as exc:
            return _result(req_id, {
                "content": [{"type": "text", "text": str(exc)}],
                "structuredContent": {"error": str(exc), "blocked": True},
                "isError": True,
            })
        except (KeyError, ValueError, TypeError) as exc:
            return _result(req_id, {
                "content": [{"type": "text", "text": str(exc)}],
                "structuredContent": {"error": str(exc)},
                "isError": True,
            })
    return _error(req_id, -32601, f"Method not found: {method}")


@app.get("/health")
def health() -> dict[str, Any]:
    return {"ok": True, "protocolVersion": PROTOCOL_VERSION, "toolCount": len(TOOLS)}


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=int(os.getenv("PORT", "8001")))
