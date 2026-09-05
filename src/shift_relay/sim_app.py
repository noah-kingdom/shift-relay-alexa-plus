from __future__ import annotations

import os
from pathlib import Path
from fastapi import FastAPI
from fastapi.responses import HTMLResponse

from .demo import DemoScenario

DB_PATH = os.getenv("SHIFT_RELAY_SIM_DB", "shiftrelay-sim.db")
scenario = DemoScenario(DB_PATH)
app = FastAPI(title="SHIFT//RELAY Alexa+ Simulation", version="0.2.0")

HTML = r'''<!doctype html>
<html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>SHIFT//RELAY</title>
<style>
body{font-family:Inter,system-ui,sans-serif;margin:0;background:#0b1020;color:#eef2ff}header{padding:28px 34px;border-bottom:1px solid #27304f}h1{margin:0;font-size:28px}.tag{color:#a5b4fc}main{display:grid;grid-template-columns:1fr 1fr;gap:20px;padding:24px}.panel{background:#11182d;border:1px solid #27304f;border-radius:16px;padding:18px}.controls{display:flex;gap:10px;flex-wrap:wrap}button{background:#eef2ff;color:#111827;border:0;border-radius:10px;padding:10px 14px;font-weight:700;cursor:pointer}.danger{background:#fecaca}.good{background:#bbf7d0}.card{border:1px solid #334155;border-radius:12px;padding:12px;margin:10px 0}.reported{border-left:5px solid #f59e0b}.verified{border-left:5px solid #22c55e}.disputed{border-left:5px solid #ef4444}.status{font-size:12px;text-transform:uppercase;letter-spacing:.06em;color:#cbd5e1}.spoken{font-size:18px;line-height:1.4;background:#0f172a;border-radius:12px;padding:14px;margin:12px 0}.trace{font-family:ui-monospace,monospace;font-size:12px;white-space:pre-wrap;max-height:340px;overflow:auto;background:#070b15;padding:12px;border-radius:10px}.hero{grid-column:1/-1}.split{display:grid;grid-template-columns:1fr 1fr;gap:12px}@media(max-width:900px){main{grid-template-columns:1fr}.hero{grid-column:auto}.split{grid-template-columns:1fr}}
</style></head>
<body><header><h1>SHIFT//RELAY</h1><div class="tag">A Trusted Operational Continuity Agent — Alexa+ simulation</div></header>
<main>
<section class="panel hero"><div class="controls"><button onclick="runFull()">Run 3-minute core flow</button><button onclick="refresh()">Refresh state</button></div><div id="spoken" class="spoken">Ready. Night shift can report exceptions hands-free.</div><div id="decision"></div></section>
<section class="panel"><h2>Operational State</h2><div id="loops"></div></section>
<section class="panel"><h2>Actions</h2><div id="actions"></div></section>
<section class="panel hero"><h2>Agent trace</h2><div id="trace" class="trace">No events yet.</div></section>
</main>
<script>
function esc(s){return String(s??'').replace(/[&<>"']/g,m=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#039;'}[m]));}
async function api(path, method='GET'){const r=await fetch(path,{method}); if(!r.ok) throw new Error(await r.text()); return r.json();}
function render(s){
 const loops=s.open_loops||[]; document.getElementById('loops').innerHTML=loops.length?loops.map(x=>`<div class="card ${esc(x.evidence_status)}"><div class="status">${esc(x.evidence_status)} · ${esc(x.status)} · ${esc(x.priority)}</div><b>${esc(x.summary)}</b><div>Owner: ${esc(x.owner||'unassigned')}</div><div>Next: ${esc(x.next_action||'follow up')}</div><div>${esc(x.last_verification_note||'Awaiting verification')}</div></div>`).join(''):'<div>No unresolved loops.</div>';
 const acts=s.actions||[]; document.getElementById('actions').innerHTML=acts.length?acts.map(a=>`<div class="card"><div class="status">${esc(a.status)} · approval ${a.approval_required?'required':'not required'}</div><b>${esc(a.action_type)}</b><div>${esc(JSON.stringify(a.payload))}</div><div>${esc(a.external_ref||'no external ref yet')}</div></div>`).join(''):'<div>No actions prepared.</div>';
 const ev=s.events||[]; document.getElementById('trace').textContent=ev.map(e=>`${e.seq}. ${e.event_type} ${e.loop_id?' loop='+e.loop_id.slice(0,8):''}${e.action_id?' action='+e.action_id.slice(0,8):''}`).join('\n')||'No events yet.';
}
async function refresh(){render(await api('/api/state'));}
async function runFull(){
 const out=await api('/api/demo/run','POST');
 const refusal=out.steps.find(x=>x.name==='safe_refusal');
 const flip=out.steps.find(x=>x.name==='evidence_flip');
 const resolution=out.steps.find(x=>x.name==='delivery_resolution');
 document.getElementById('spoken').innerHTML=`<b>Decision changes with evidence.</b><br>${esc(refusal.spoken)}<br><br>${esc(flip.spoken)}<br><br>${esc(resolution.spoken)}`;
 document.getElementById('decision').innerHTML=`<div class="split"><div class="card reported"><div class="status">UNVERIFIED → REFUSE</div><b>Freezer delivery</b><div>No supplier action allowed.</div></div><div class="card verified"><div class="status">NEW EVIDENCE → VERIFIED → ACT</div><b>Same freezer delivery</b><div>Decision flips only after carrier evidence arrives.</div></div></div>`;
 render(out.snapshot);
}
refresh();
</script></body></html>'''


@app.get("/", response_class=HTMLResponse)
def index() -> str:
    return HTML


@app.post("/api/demo/run")
def run_demo() -> dict:
    return scenario.run_full()


@app.post("/api/demo/reset")
def reset_demo() -> dict:
    return scenario.reset()


@app.get("/api/state")
def get_state() -> dict:
    return scenario.snapshot()
