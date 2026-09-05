#!/usr/bin/env python3
"""Official MCP Python SDK end-to-end proof client for SHIFT//RELAY.

Requires: mcp>=1.28,<2
Server: python -m shift_relay.mcp_server (Streamable HTTP at /mcp)

The proof deliberately injects carrier evidence from a *separate process* so the
Evidence Flip is not an in-process test fixture.
"""
from __future__ import annotations

import argparse
import asyncio
import json
import os
from importlib.metadata import version as package_version
from pathlib import Path
import subprocess
import sys
import time
from typing import Any

from mcp import ClientSession
from mcp.client.streamable_http import streamable_http_client


def normalize(result: Any) -> dict[str, Any]:
    structured = getattr(result, "structuredContent", None)
    if structured is None:
        structured = getattr(result, "structured_content", None)
    is_error = bool(getattr(result, "isError", getattr(result, "is_error", False)))
    text = None
    content = getattr(result, "content", None) or []
    if content:
        text = getattr(content[0], "text", None)
    if structured is None and text:
        try:
            structured = json.loads(text)
        except Exception:
            structured = {"text": text}
    return {"structured": structured, "is_error": is_error, "text": text}


def log(event: str, **payload: Any) -> None:
    print(json.dumps({"ts": time.time(), "event": event, **payload}, sort_keys=True, default=str), flush=True)


async def main_async(url: str, evidence_file: Path) -> None:
    log("client_environment", mcp_sdk_version=package_version("mcp"), python=sys.version.split()[0], url=url)
    # v1.x has returned both 2- and 3-item transport tuples across maintenance releases.
    async with streamable_http_client(url) as streams:
        read_stream, write_stream = streams[0], streams[1]
        async with ClientSession(read_stream, write_stream) as session:
            init = await session.initialize()
            negotiated = str(getattr(init, "protocolVersion", getattr(init, "protocol_version", None)))
            server_info = getattr(init, "serverInfo", getattr(init, "server_info", None))
            log("initialize", server=str(server_info), protocol=negotiated)
            advertised_version = str(getattr(server_info, "version", ""))
            if advertised_version and advertised_version != "0.4.0":
                raise AssertionError(f"Expected SHIFT//RELAY serverInfo.version 0.4.0, got {advertised_version}")
            if negotiated and negotiated != "None" and negotiated < "2025-11-25":
                raise AssertionError(f"Negotiated MCP protocol {negotiated} is older than Alexa+ minimum 2025-11-25")

            tools = await session.list_tools()
            names = [tool.name for tool in tools.tools]
            log("tools_list", count=len(names), tools=names)
            if len(names) != 11:
                raise AssertionError(f"Expected 11 MCP tools, got {len(names)}: {names}")

            async def call(name: str, arguments: dict[str, Any]) -> dict[str, Any]:
                t0 = time.perf_counter()
                try:
                    result = await session.call_tool(name, arguments=arguments)
                    norm = normalize(result)
                except Exception as exc:
                    norm = {"structured": None, "is_error": True, "text": repr(exc)}
                ms = (time.perf_counter() - t0) * 1000
                log("tool_call", tool=name, latency_ms=round(ms, 3), result=norm)
                return norm

            shift = (await call("start_shift", {"site_id": "qsr-17", "worker_id": "alex", "shift_type": "closing"}))["structured"]
            sid = shift["shift_id"]
            delivery = (await call("report_exception", {
                "site_id": "qsr-17", "shift_id": sid, "created_by": "alex",
                "summary": "The chilled-goods truck seems to have missed its drop.",
                "category": "delivery", "subject_key": "freezer_delivery", "risk": "high", "priority": "high",
            }))["structured"]
            cups = (await call("report_exception", {
                "site_id": "qsr-17", "shift_id": sid, "created_by": "alex",
                "summary": "We have barely any 20-ounce cups left for the morning rush.",
                "category": "inventory", "subject_key": "large_cups", "risk": "high", "priority": "urgent",
            }))["structured"]

            dv = (await call("verify_open_loop", {"loop_id": delivery["id"]}))["structured"]
            cv = (await call("verify_open_loop", {"loop_id": cups["id"]}))["structured"]
            assert dv["verification"]["outcome"] == "inconclusive", dv
            assert cv["verification"]["outcome"] == "verified", cv

            blocked = await call("prepare_action", {
                "loop_id": delivery["id"], "action_type": "supplier_followup",
                "payload": {"supplier": "FreezerCo"}, "risk": "high",
            })
            if not blocked["is_error"]:
                raise AssertionError("Unverified high-risk delivery action was not rejected")
            log("safe_refusal_proved", loop_id=delivery["id"])

            # External process changes carrier evidence; server process is untouched.
            cmd = [sys.executable, "scripts/inject_carrier_evidence.py", "--evidence-file", str(evidence_file), "--exception", "missed_delivery"]
            env = dict(os.environ)
            env["PYTHONPATH"] = str(Path.cwd() / "src") + os.pathsep + env.get("PYTHONPATH", "")
            proc = subprocess.run(cmd, check=True, capture_output=True, text=True, env=env)
            log("external_carrier_event", stdout=proc.stdout.strip())

            flipped = (await call("verify_open_loop", {"loop_id": delivery["id"]}))["structured"]
            assert flipped["verification"]["outcome"] == "verified", flipped
            assert flipped["loop"]["id"] == delivery["id"]
            log("evidence_flip_proved", loop_id=delivery["id"], from_state="unverified", to_state="verified")

            prepared = (await call("prepare_action", {
                "loop_id": delivery["id"], "action_type": "supplier_followup",
                "payload": {"supplier": "FreezerCo", "reason": "verified missed delivery"}, "risk": "high",
            }))["structured"]
            action_id = prepared["id"]
            approved = (await call("approve_action", {"action_id": action_id, "approved_by": "jamie"}))["structured"]
            assert approved["status"] == "approved"
            executed = (await call("execute_approved_action", {"action_id": action_id}))["structured"]
            assert executed["status"] == "executed"
            confirmed = (await call("confirm_action_result", {"action_id": action_id}))["structured"]
            assert confirmed["status"] == "confirmed"
            log("closed_loop_proved", action_id=action_id, external_ref=confirmed.get("external_ref"))
            log("OFFICIAL_MCP_E2E_PASS")


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--url", default="http://127.0.0.1:8000/mcp")
    parser.add_argument("--evidence-file", default="official-proof-evidence.json")
    args = parser.parse_args()
    asyncio.run(main_async(args.url, Path(args.evidence_file).resolve()))


if __name__ == "__main__":
    main()
