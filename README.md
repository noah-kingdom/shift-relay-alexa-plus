# SHIFT//RELAY

**A Trusted Operational Continuity Agent for Alexa+**

> Work should not disappear when people change shifts. And an agent should not act on what it cannot verify.

SHIFT//RELAY converts messy frontline speech into durable **Operational State**, carries only unresolved work across people and sessions, pursues verification, gates risky actions behind explicit human approval, and closes the loop by confirming the external result.

This repository is a working MVP for the **Build, Ship, Shape: Amazon Developer Hackathon 2026 — Alexa+ Track**.

## Why it is not a voice task list

The durable object is not a transcript or todo. It is an auditable state machine with:

- **Evidence state**: `reported`, `verified`, `disputed`
- **Operational state**: `open`, `blocked`, `actioned`, `completed`
- **Priority and ownership**
- **Verification evidence** and provenance
- **Approval state** for high-risk actions
- **External execution evidence** and closed-loop confirmation
- **Cross-shift persistence** independent of the worker/session that created it

The central safety rule is simple:

**REPORTED != VERIFIED**

## Core 3-minute scenario

Night shift says:

> “The freezer delivery never arrived, and we're almost out of large cups.”

The simulation decomposes that one utterance into two typed operational exceptions. It then checks deterministic evidence sources:

1. **Large cups** — inventory shows 4% on hand against a 15% threshold -> **VERIFIED**.
2. **Freezer delivery** — a delivery was scheduled but no receipt scan exists -> remains **REPORTED / BLOCKED**, not silently upgraded.

Morning shift starts as a different worker. The agent restores only unresolved work and says, in effect:

> “The cup shortage is verified, so I can prepare an action. The freezer delivery is still unverified, so I will not act on it yet.”

It then demonstrates both sides of trustworthy autonomy:

- **UNVERIFIED -> REFUSE**: a high-risk supplier escalation cannot even be prepared.
- **VERIFIED -> PREPARE -> HUMAN APPROVAL -> EXECUTE -> CONFIRM**: a 10-case restock request is approved, executed, and externally confirmed before the loop closes.

## Architecture

```text
Alexa+ / Web Simulation
        |
        v
MCP tool surface (Streamable HTTP)
        |
        v
Trusted Operational State Engine
  |         |          |
  |         |          +-- Action approval + execution + confirmation
  |         +------------- Verification providers
  +----------------------- SQLite durable state + event audit trail
```

### Alexa+ / MCP path

`src/shift_relay/mcp_server.py` exposes the following tools:

- `start_shift`
- `report_exception`
- `verify_open_loop`
- `pursue_open_loops`
- `get_open_loops`
- `close_shift`
- `resume_shift`
- `prepare_action`
- `approve_action`
- `execute_approved_action`
- `confirm_action_result`

The adapter uses **Streamable HTTP** and is intentionally stateless at the transport layer; operational continuity lives in SQLite, not in an MCP connection session.

### Web simulation path

`src/shift_relay/sim_app.py` is a fully runnable simulation that needs no external model/API. It exists so judges can see the complete agent behavior deterministically even if an Alexa+ add-on environment is unavailable.

## Run the tested Web Simulation

```bash
python -m venv .venv
# activate the venv
pip install -e .
uvicorn shift_relay.sim_app:app --app-dir src --host 127.0.0.1 --port 8080
```

Open `http://127.0.0.1:8080` and click **Run 3-minute core flow**.

## Run tests

```bash
pip install -e ".[dev]"
pytest -q
```

Current sealed local result: **13 passed, 2 skipped**. The two skips require an official MCP environment; the official MCP SDK and Inspector path was separately proven on a networked machine.

The tests cover:

- cross-shift persistence
- no silent evidence upgrade
- verified vs inconclusive evidence
- refusal to prepare high-risk actions from unverified state
- refusal to execute high-risk actions without human approval
- closed-loop external confirmation
- priority ordering
- full demo safe-refusal path
- one utterance -> two typed exceptions

## Run the MCP server

The current production adapter intentionally pins the official MCP Python SDK v1 line because Amazon AgentCore's current FastMCP deployment examples use that API and it supports the required 2025-era protocol path.

```bash
pip install -e ".[mcp]"
python -m shift_relay.mcp_server
```

Expected endpoint: `http://localhost:8000/mcp`.

Then test with MCP Inspector or an MCP client.

> Proof status: the production adapter has been executed with the official MCP Python SDK over Streamable HTTP. The standard MCP Inspector connected to `http://127.0.0.1:8000/mcp`, discovered all 11 tools, and manually completed the fail-closed -> Evidence Flip -> approval -> execution -> confirmation chain. See `OFFICIAL_MCP_INSPECTOR_PROOF_2026-09-02.md` and `EVIDENCE_MANIFEST.md`.

## Amazon Bedrock AgentCore path

Amazon Bedrock AgentCore Runtime supports Streamable HTTP MCP servers at `0.0.0.0:8000/mcp`. The server is configured with `host="0.0.0.0"` and `stateless_http=True` for that path. Operational state is externalized to SQLite for the MVP; a production deployment could replace SQLite with a managed durable store without changing the tool contract.

## Safety model

1. Human speech starts as **reported**, never automatically verified.
2. Verification can promote an item only when a configured evidence source supports it.
3. High-risk actions cannot be prepared from unverified state.
4. High-risk actions cannot execute without explicit approval.
5. Execution is not success: the external result must be confirmed before the loop completes.
6. Every state transition emits an audit event.

## Repository map

```text
src/shift_relay/core.py       Durable state, verification, approval, action audit
src/shift_relay/nlp.py        Deterministic demo utterance decomposition
src/shift_relay/demo.py       End-to-end deterministic scenario
src/shift_relay/sim_app.py    Web Alexa+ simulation / visual board
src/shift_relay/mcp_server.py MCP Streamable HTTP adapter
tests/test_core.py            Regression and safety tests
DEMO_SCRIPT.md                Sub-3-minute English demo script
AI_REVIEW_PACKET.md           Blind re-review packet after implementation
FRICTION_LOG_DRAFT.md         Hackathon friction-log working draft
PRODUCT_FEEDBACK_DRAFT.md     Submission feedback working draft
```

## What is real vs simulated

**Real in this MVP:** SQLite persistence, typed state transitions, evidence gating, approval gating, event audit, deterministic action execution/confirmation, web API, visual board, tests.

**Simulated by explicit design:** inventory source, delivery receipt source, purchase-order system. They are deterministic local providers and are labeled `*_demo`; the repository does not pretend that a real POS, supplier, or inventory system was contacted.

**Externally validated:** official MCP SDK runtime connection and standard MCP Inspector end-to-end behavior.

**Not claimed as completed:** live Alexa+ add-on invocation and optional AgentCore deployment in an AWS account.

## License

MIT — see `LICENSE`.

## Winner-gate proof commands

For the official MCP v1 SDK / Streamable HTTP end-to-end proof on a networked Windows PC:

```powershell
powershell -ExecutionPolicy Bypass -File .\scripts\run_official_mcp_proof.ps1
```

See `OFFICIAL_MCP_PROOF_RUNBOOK.md` for Inspector capture steps and evidence claims.


## Evidence integrity / submission demo

The local deterministic parser (`src/shift_relay/nlp.py`) exists only to keep the public Web simulation reproducible without an external model. It is **not** evidence of Alexa+ NLU.

For the submission claim that one natural-language utterance becomes multiple operational issues, use the live Alexa+ -> official MCP path and show the resulting `report_exception` tool calls. See `DEMO_RECORDING_POLICY.md` and `ALEXA_LIVE_PROOF_RUNBOOK.md`.

The test evidence is deliberately split into three layers: local core/safety tests, SDK-independent MCP compatibility-harness tests, and official MCP SDK / Inspector proof. These must not be conflated.

For submission status and exact observed ids, see `CURRENT_STATUS_2026-09-05.md` and `EVIDENCE_MANIFEST.md`.
