# SHIFT//RELAY — Evidence-Grounded Operational Agent

**Nebius Token Factory × NVIDIA Nemotron × Tavily**

> Evidence changes what the agent is allowed to do.

SHIFT//RELAY is an operational agent that separates **what a human reported** from **what external evidence verifies**. A frontline claim begins as `REPORTED`. NVIDIA Nemotron, served through Nebius Token Factory, turns the natural-language report into a typed operational issue without being allowed to certify the claim as true. Tavily then retrieves external evidence. A deterministic authority policy decides whether the issue may transition to `VERIFIED` and whether a high-risk action may move from `BLOCKED` to `PREPARED`. Human approval remains required.

## Live demo

https://shift-relay-nebius-final.onrender.com/

The demonstration uses a product-safety recall scenario:

```text
Human report
    ↓
Nebius Token Factory → NVIDIA Nemotron
    ↓
REPORTED
    ↓
high-risk action attempt → BLOCKED
    ↓
Tavily live search/extract → exact U.S. CPSC primary source
    ↓
deterministic evidence authority
    ↓
VERIFIED
    ↓
action → PREPARED
    ↓
HUMAN APPROVAL REQUIRED
```

## Why the model cannot silently promote evidence

Nemotron is deliberately asked to **understand, not verify**. The model can propose a typed issue, but evidence authority belongs to deterministic policy. This prevents an agent from turning a confident paraphrase of a human claim into permission to act.

## Run locally

From the root of the existing SHIFT//RELAY repository:

```bash
python -m venv .venv
# activate .venv
pip install -e .
export NEBIUS_API_KEY='YOUR_SECRET'
export TAVILY_API_KEY='YOUR_SECRET'
PYTHONPATH=src:. python -m uvicorn nebius_submission.app:app --host 127.0.0.1 --port 8080
```

PowerShell:

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -e .
$env:NEBIUS_API_KEY='YOUR_SECRET'
$env:TAVILY_API_KEY='YOUR_SECRET'
$env:PYTHONPATH="$PWD\src;$PWD"
python -m uvicorn nebius_submission.app:app --host 127.0.0.1 --port 8080
```

Open `http://127.0.0.1:8080` and click **Run live authority proof** once.

## Required environment variables

- `NEBIUS_API_KEY` — Nebius Token Factory key
- `TAVILY_API_KEY` — Tavily key

Optional:

- `NEBIUS_MODEL` — defaults to `nvidia/Nemotron-3_5-Lightning`
- `NEBIUS_BASE_URL` — defaults to `https://api.tokenfactory.nebius.com/v1/`
- `SHIFT_RELAY_NEBIUS_DB` — SQLite path

**Never commit API keys.**

## What is live vs deterministic

**Live:**
- runtime inference call to NVIDIA Nemotron through Nebius Token Factory
- Tavily runtime search/extract
- retrieval of the exact U.S. CPSC primary page

**Deterministic by design:**
- whether retrieved evidence satisfies the strict verification policy
- state transition from `REPORTED` to `VERIFIED`
- refusal to prepare a high-risk action before verification
- requirement for human approval after preparation

## Significant update from the earlier Alexa+/MCP build

The earlier SHIFT//RELAY build demonstrated durable operational state and evidence-gated action control in an Alexa+/MCP setting. During the Nebius/NVIDIA submission period, the core runtime path was substantially changed:

- deterministic demo parsing → **live NVIDIA Nemotron decomposition through Nebius Token Factory**
- local/demo evidence → **live Tavily external evidence retrieval**
- generic evidence gate → **strict primary-source evidence authority**
- action gating tied directly to the new live evidence path

This is a functional change to the core behavior, not a cosmetic rebrand.

## License

The parent repository is MIT-licensed. See `LICENSE`.
