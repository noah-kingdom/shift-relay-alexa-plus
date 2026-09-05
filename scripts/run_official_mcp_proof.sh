#!/usr/bin/env bash
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT"
VENV="$ROOT/.venv-official-mcp"
EVIDENCE="$ROOT/official-proof-evidence.json"
DB="$ROOT/official-proof-state.db"
SERVER_LOG="$ROOT/OFFICIAL_MCP_SERVER_LOG.txt"
CLIENT_LOG="$ROOT/OFFICIAL_MCP_CLIENT_PROOF.jsonl"
python -m venv "$VENV"
source "$VENV/bin/activate"
python -m pip install --upgrade pip
python -m pip install 'mcp>=1.28,<2' 'fastapi>=0.115' 'uvicorn>=0.30' 'pytest>=8' 'httpx>=0.27'
rm -f "$EVIDENCE" "$DB" "$SERVER_LOG" "$CLIENT_LOG"
export PYTHONPATH="$ROOT/src${PYTHONPATH:+:$PYTHONPATH}"
export SHIFT_RELAY_DB="$DB"
export SHIFT_RELAY_EVIDENCE_FILE="$EVIDENCE"
python -m shift_relay.mcp_server >"$SERVER_LOG" 2>&1 &
SERVER_PID=$!
trap 'kill "$SERVER_PID" 2>/dev/null || true' EXIT
sleep 3
python scripts/official_mcp_e2e.py --url http://127.0.0.1:8000/mcp --evidence-file "$EVIDENCE" | tee "$CLIENT_LOG"
echo "OFFICIAL MCP SDK E2E: PASS"
echo "Next visual certification: npx -y @modelcontextprotocol/inspector and connect to http://127.0.0.1:8000/mcp"
