"""SHIFT//RELAY MCP server adapter.

This adapter uses the official MCP Python SDK / FastMCP and Streamable HTTP.
The durable operational state lives in SQLite and therefore survives MCP/Alexa+
session boundaries. The web simulation remains runnable without the MCP SDK.
"""
from __future__ import annotations

import os
from mcp.server.fastmcp import FastMCP

from .core import DemoActionExecutor, DemoVerifier, Priority, RiskLevel, ShiftStore, summarize_handoff

DB_PATH = os.getenv("SHIFT_RELAY_DB", "shiftrelay.db")
SERVER_VERSION = os.getenv("SHIFT_RELAY_SERVER_VERSION", "0.4.0")
store = ShiftStore(DB_PATH)
verifier = DemoVerifier(os.getenv("SHIFT_RELAY_EVIDENCE_FILE", "shiftrelay-evidence.json"))
executor = DemoActionExecutor()

mcp = FastMCP(
    "SHIFT//RELAY",
    instructions=(
        "Maintain trusted operational state across frontline shifts. Reported human statements are not verified facts. "
        "Use verification tools before high-risk actions. Low-risk recording may be autonomous. High-risk external actions "
        "require explicit human approval. Pursue unresolved loops and confirm the result after execution."
    ),
    host="0.0.0.0",
    stateless_http=True,
    json_response=True,
)
# FastMCP v1 does not expose a public `version=` constructor argument.
# Pin the underlying low-level MCP Server metadata to the application version
# so initialize.serverInfo.version identifies SHIFT//RELAY, not the SDK build.
mcp._mcp_server.version = SERVER_VERSION  # type: ignore[attr-defined]


@mcp.tool()
def start_shift(site_id: str, worker_id: str, shift_type: str) -> dict:
    """Start a frontline shift and return a durable shift id."""
    return store.start_shift(site_id, worker_id, shift_type)


@mcp.tool()
def report_exception(site_id: str, shift_id: str, created_by: str, summary: str, category: str,
                     subject_key: str, risk: str = "low", priority: str = "medium",
                     owner: str | None = None, due: str | None = None,
                     next_action: str | None = None) -> dict:
    """Create one operational loop. Call once per distinct issue extracted from a user utterance."""
    item = store.report_exception(
        site_id=site_id, shift_id=shift_id, created_by=created_by, summary=summary,
        category=category, subject_key=subject_key, risk=RiskLevel(risk), priority=Priority(priority),
        owner=owner, due=due, next_action=next_action,
    )
    return item.__dict__


@mcp.tool()
def verify_open_loop(loop_id: str) -> dict:
    """Check configured evidence sources. Never convert an inconclusive report into a verified fact."""
    loop, result = store.verify_loop(loop_id, verifier)
    return {"loop": loop.__dict__, "verification": result.__dict__}


@mcp.tool()
def pursue_open_loops(site_id: str) -> dict:
    """Proactively re-check unresolved, unverified loops using available evidence sources."""
    return {"results": store.pursue_open_loops(site_id, verifier)}


@mcp.tool()
def get_open_loops(site_id: str) -> dict:
    """Return unresolved operational work independent of which worker/session created it."""
    loops = store.get_open_loops(site_id)
    return {"open_loops": [x.__dict__ for x in loops], "spoken_handoff": summarize_handoff(loops)}


@mcp.tool()
def close_shift(shift_id: str) -> dict:
    """Close a shift while unresolved operational loops remain durable."""
    return store.close_shift(shift_id)


@mcp.tool()
def resume_shift(site_id: str, worker_id: str, shift_type: str) -> dict:
    """Start a new shift and surface only unresolved work carried over from prior shifts."""
    result = store.resume_shift(site_id, worker_id, shift_type)
    result["spoken_handoff"] = summarize_handoff(store.get_open_loops(site_id))
    return result


@mcp.tool()
def prepare_action(loop_id: str, action_type: str, payload: dict, risk: str = "high") -> dict:
    """Prepare an action. High-risk actions are rejected if the underlying state is unverified."""
    return store.prepare_action(loop_id=loop_id, action_type=action_type, payload=payload, risk=RiskLevel(risk)).__dict__


@mcp.tool()
def approve_action(action_id: str, approved_by: str) -> dict:
    """Record explicit human approval for a prepared high-risk action."""
    return store.approve_action(action_id, approved_by).__dict__


@mcp.tool()
def execute_approved_action(action_id: str) -> dict:
    """Execute an action only after required approval; returns external execution evidence."""
    return store.execute_action(action_id, executor).__dict__


@mcp.tool()
def confirm_action_result(action_id: str) -> dict:
    """Close the loop by checking the external system and confirming the executed action succeeded."""
    return store.confirm_action(action_id, executor).__dict__


if __name__ == "__main__":
    mcp.run(transport="streamable-http")
