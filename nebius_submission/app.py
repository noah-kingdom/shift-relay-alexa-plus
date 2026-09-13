from __future__ import annotations

import json
import os
import re
from urllib import error, request
from urllib.parse import urlparse

from fastapi import FastAPI, HTTPException
from fastapi.responses import HTMLResponse

from shift_relay.core import (
    EvidenceStatus,
    Priority,
    RiskLevel,
    ShiftStore,
    VerificationResult,
)

SITE = "nebius-final-01"
DB = os.getenv("SHIFT_RELAY_NEBIUS_DB", "/tmp/shiftrelay-nebius-final.db")
NEBIUS_BASE = os.getenv("NEBIUS_BASE_URL", "https://api.tokenfactory.nebius.com/v1/").rstrip("/") + "/"
MODEL = os.getenv("NEBIUS_MODEL", "nvidia/Nemotron-3_5-Lightning")
CPSC = "https://www.cpsc.gov/Recalls/2025/Curtis-International-Recalls-Frigidaire-brand-Minifridges-Due-to-Fire-and-Burn-Hazards-More-Than-700-000-Reported-in-Property-Damage"
CANON = "curtis-international-recalls-frigidaire-brand-minifridges-due-to-fire-and-burn-hazards-more-than-700-000-reported-in-property-damage"

store = ShiftStore(DB)
app = FastAPI(title="SHIFT//RELAY — Strict Primary Evidence Authority")


def post_json(url: str, token: str, payload: dict) -> dict:
    req = request.Request(
        url,
        data=json.dumps(payload).encode(),
        method="POST",
        headers={
            "Authorization": f"Bearer {token}",
            "Content-Type": "application/json",
            "Accept": "application/json",
            "User-Agent": "shift-relay-nebius-final/2.0",
        },
    )
    try:
        with request.urlopen(req, timeout=40) as response:
            return json.loads(response.read().decode())
    except error.HTTPError as exc:
        raise HTTPException(exc.code, exc.read().decode(errors="replace")[:1000]) from exc
    except error.URLError as exc:
        raise HTTPException(502, f"Network error: {exc}") from exc


def strict_primary(item: dict) -> bool:
    url = str(item.get("url") or "")
    host = (urlparse(url).hostname or "").lower().rstrip(".")
    path = url.lower()
    text = " ".join(
        [
            str(item.get("title") or ""),
            str(item.get("content") or ""),
            str(item.get("raw_content") or ""),
        ]
    ).lower()
    return (
        (host == "cpsc.gov" or host.endswith(".cpsc.gov"))
        and CANON in path
        and "efmis129" in text
        and ("recall" in text or "recalled" in text)
        and "fire" in text
        and ("burn" in text or "hazard" in text)
    )


class Provider:
    def __init__(self, decision: dict):
        self.decision = decision

    def verify(self, loop):
        if self.decision["verified"]:
            return VerificationResult(
                outcome="verified",
                note="Exact CPSC Frigidaire EFMIS129 recall page matches model and fire/burn hazard policy.",
                source=self.decision["source"],
                observed=self.decision,
            )
        return VerificationResult(
            outcome="inconclusive",
            note="No exact CPSC EFMIS129 primary page satisfied the strict policy.",
            source="Tavily evidence scout",
            observed=self.decision,
        )


def runtime_status() -> dict:
    return {
        "nebius_configured": bool(os.getenv("NEBIUS_API_KEY")),
        "tavily_configured": bool(os.getenv("TAVILY_API_KEY")),
        "model": MODEL,
        "secrets_exposed": False,
    }


@app.get("/api/state")
def api_state():
    return {"runtime": runtime_status(), "snapshot": store.snapshot(SITE)}


@app.post("/api/run")
def api_run():
    nebius_key = os.getenv("NEBIUS_API_KEY", "").strip()
    tavily_key = os.getenv("TAVILY_API_KEY", "").strip()
    if not nebius_key or not tavily_key:
        raise HTTPException(503, "NEBIUS_API_KEY and TAVILY_API_KEY must be configured.")

    store.reset()
    shift = store.start_shift(SITE, "frontline", "public-live-demo")
    report = (
        "A Frigidaire EFMIS129 mini fridge in the break room may be recalled for a fire risk. "
        "Please remove it from service and notify facilities."
    )
    system = (
        'Return JSON only. Convert the report into typed operational issues. '
        'Do not decide whether claims are true. Never mark anything verified. '
        'Schema: {"issues":[{"summary":"...","category":"...","subject_key":"..."}]}'
    )
    raw = post_json(
        NEBIUS_BASE + "chat/completions",
        nebius_key,
        {
            "model": MODEL,
            "messages": [
                {"role": "system", "content": system},
                {"role": "user", "content": report},
            ],
            "temperature": 0,
            "max_tokens": 500,
            "chat_template_kwargs": {"enable_thinking": False},
        },
    )
    content = raw["choices"][0]["message"].get("content") or ""
    match = re.search(r"\\{.*\\}", content, re.S)
    parsed = json.loads(match.group(0) if match else content)
    item = (parsed.get("issues") or [{}])[0]
    summary = str(item.get("summary") or "Frigidaire EFMIS129 mini fridge may be recalled for fire risk")

    loop = store.report_exception(
        site_id=SITE,
        shift_id=shift["shift_id"],
        created_by="frontline",
        summary=summary,
        category=str(item.get("category") or "product_safety_recall"),
        subject_key=str(item.get("subject_key") or "frigidaire_efmis129"),
        risk=RiskLevel.HIGH,
        priority=Priority.HIGH,
        next_action="quarantine asset and notify facilities",
    )

    try:
        store.prepare_action(
            loop_id=loop.id,
            action_type="facilities_recall_escalation",
            payload={"requested_step": "quarantine asset and notify facilities"},
            risk=RiskLevel.HIGH,
        )
        blocked = False
        reason = "unexpectedly allowed"
    except PermissionError as exc:
        blocked = True
        reason = str(exc)

    search = post_json(
        "https://api.tavily.com/search",
        tavily_key,
        {
            "query": "site:cpsc.gov/Recalls/2025 Curtis International Frigidaire EFMIS129 minifridges fire burn hazards 700000",
            "search_depth": "advanced",
            "max_results": 10,
            "include_domains": ["cpsc.gov"],
            "include_raw_content": True,
        },
    )
    hits = [x for x in (search.get("results") or []) if isinstance(x, dict) and strict_primary(x)]
    path = "tavily_search_exact_primary"
    extract_request_id = None
    if not hits:
        extract = post_json(
            "https://api.tavily.com/extract",
            tavily_key,
            {
                "urls": CPSC,
                "query": "Frigidaire EFMIS129 recall fire burn hazard model serial numbers",
                "chunks_per_source": 5,
                "extract_depth": "advanced",
                "include_images": False,
                "format": "markdown",
            },
        )
        extract_request_id = extract.get("request_id")
        for candidate in extract.get("results") or []:
            if isinstance(candidate, dict) and strict_primary(candidate):
                hits = [candidate]
                break
        path = "tavily_extract_canonical_primary"

    decision = {
        "verified": bool(hits),
        "search_request_id": search.get("request_id"),
        "extract_request_id": extract_request_id,
        "trusted_hit_count": len(hits),
        "primary": hits[0] if hits else None,
        "canonical_url": CPSC,
        "policy": "exact_cpsc_canonical_page + EFMIS129 + recall + fire/burn hazard",
        "path": path,
        "source": "Tavily live retrieval -> exact U.S. CPSC EFMIS129 primary source",
    }

    updated, _verification = store.verify_loop(loop.id, Provider(decision))
    action = None
    if updated.evidence_status == EvidenceStatus.VERIFIED.value:
        action = store.prepare_action(
            loop_id=loop.id,
            action_type="facilities_recall_escalation",
            payload={
                "asset": "Frigidaire EFMIS129 mini fridge",
                "evidence": "Exact CPSC EFMIS129 primary recall page retrieved live through Tavily",
                "requested_step": "quarantine asset and notify facilities",
            },
            risk=RiskLevel.HIGH,
        )

    return {
        "report": report,
        "nemotron": {
            "model": MODEL,
            "issue": {
                "summary": summary,
                "category": item.get("category"),
                "subject_key": item.get("subject_key"),
            },
        },
        "before": {
            "evidence_status": "REPORTED",
            "action_gate": "BLOCKED" if blocked else "UNEXPECTED",
            "reason": reason,
        },
        "evidence": decision,
        "after": {
            "evidence_status": updated.evidence_status,
            "action_gate": "PREPARED" if action else "BLOCKED",
            "human_approval_required": bool(action.approval_required) if action else True,
        },
        "snapshot": store.snapshot(SITE),
    }


HTML = r'''<!doctype html>
<html><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>SHIFT//RELAY Nebius Final</title>
<style>
body{font-family:Inter,system-ui;background:#07101f;color:#edf4ff;margin:0}main{max-width:1120px;margin:auto;padding:42px 24px}h1{font-size:42px;margin:8px 0}.sub{color:#b8c8e8;font-size:18px;line-height:1.55}.chips{display:flex;gap:8px;flex-wrap:wrap;margin:18px 0}.chip,.card{border:1px solid #29405f;border-radius:14px;background:#0d1a2c;padding:12px}.grid{display:grid;grid-template-columns:repeat(3,1fr);gap:14px;margin:24px 0}.big{font-size:24px;font-weight:800}.reported{color:#ffc857}.verified{color:#53e29c}.prepared{color:#74b8ff}button{padding:13px 18px;border-radius:10px;border:0;font-weight:800;cursor:pointer}pre{white-space:pre-wrap;background:#050a12;padding:16px;border-radius:12px;overflow:auto}@media(max-width:800px){.grid{grid-template-columns:1fr}}
</style></head><body><main>
<div>Nebius Token Factory × NVIDIA Nemotron × Tavily</div>
<h1>Evidence changes what the agent is allowed to do.</h1>
<div class="sub">Nemotron understands. Tavily retrieves the exact primary source. SHIFT//RELAY decides when evidence is strong enough to change action authority.</div>
<div id="chips" class="chips"></div>
<div class="grid"><div class="card"><b>1 · Human report</b><div>Claim — not a fact yet</div></div><div class="card"><b>2 · Nemotron</b><div>Typed issue — understanding, not verification</div></div><div class="card"><b>3 · Authority</b><div>REPORTED → VERIFIED · BLOCKED → PREPARED</div></div></div>
<button onclick="runProof()">Run live authority proof</button>
<div id="out" class="card" style="margin-top:18px">Ready.</div><pre id="trace"></pre>
</main><script>
async function refresh(){let r=await fetch('/api/state');let s=await r.json();chips.innerHTML=`<span class="chip">NEBIUS ${s.runtime.nebius_configured?'READY':'NOT SET'}</span><span class="chip">NEMOTRON ${s.runtime.model}</span><span class="chip">TAVILY ${s.runtime.tavily_configured?'READY':'NOT SET'}</span><span class="chip">SHIFT//RELAY STRICT POLICY AUTHORITY</span>`}
async function runProof(){out.textContent='Running live Nemotron + Tavily strict-primary flow...';let r=await fetch('/api/run',{method:'POST'});let x=await r.json();if(!r.ok){out.textContent=x.detail||JSON.stringify(x);return}let p=x.evidence.primary;out.innerHTML=`<div class="big reported">BEFORE: ${x.before.evidence_status} · ${x.before.action_gate}</div><p>${x.nemotron.issue.summary}</p><div class="big verified">EVIDENCE: ${x.evidence.verified?'VERIFIED':'INCONCLUSIVE'} · exact primary hits ${x.evidence.trusted_hit_count}</div><p>Path: ${x.evidence.path}</p><p>${p?'<a style="color:#8fc8ff" href="'+x.evidence.canonical_url+'" target="_blank">Open exact CPSC EFMIS129 primary evidence</a>':''}</p><div class="big prepared">AFTER: ${x.after.evidence_status.toUpperCase()} · ${x.after.action_gate}</div><p>Human approval required: ${x.after.human_approval_required}</p>`;trace.textContent=JSON.stringify({search_request_id:x.evidence.search_request_id,extract_request_id:x.evidence.extract_request_id,policy:x.evidence.policy,canonical_url:x.evidence.canonical_url,events:x.snapshot.events},null,2)}
refresh()
</script></body></html>'''


@app.get("/", response_class=HTMLResponse)
def index():
    return HTML
