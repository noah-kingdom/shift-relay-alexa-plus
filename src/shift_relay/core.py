from __future__ import annotations

from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from enum import Enum
import json
from pathlib import Path
import sqlite3
from typing import Any, Iterable, Protocol
import uuid


def utcnow() -> str:
    return datetime.now(timezone.utc).isoformat()


class EvidenceStatus(str, Enum):
    REPORTED = "reported"
    VERIFIED = "verified"
    DISPUTED = "disputed"


class LoopStatus(str, Enum):
    OPEN = "open"
    BLOCKED = "blocked"
    ACTIONED = "actioned"
    COMPLETED = "completed"


class RiskLevel(str, Enum):
    LOW = "low"
    HIGH = "high"


class Priority(str, Enum):
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"
    URGENT = "urgent"


class ActionStatus(str, Enum):
    PREPARED = "prepared"
    APPROVED = "approved"
    EXECUTED = "executed"
    CONFIRMED = "confirmed"
    REJECTED = "rejected"
    FAILED = "failed"


@dataclass(frozen=True)
class OpenLoop:
    id: str
    site_id: str
    shift_id: str
    summary: str
    category: str
    subject_key: str
    evidence_status: str
    status: str
    risk: str
    priority: str
    owner: str | None
    due: str | None
    next_action: str | None
    last_verification_note: str | None
    last_verified_at: str | None
    created_by: str
    created_at: str
    updated_at: str


@dataclass(frozen=True)
class VerificationResult:
    outcome: str  # verified | inconclusive | disputed
    note: str
    source: str
    observed: dict[str, Any]


@dataclass(frozen=True)
class ActionRecord:
    id: str
    loop_id: str
    action_type: str
    payload: dict[str, Any]
    risk: str
    status: str
    approval_required: bool
    approved_by: str | None
    approved_at: str | None
    external_ref: str | None
    result: dict[str, Any] | None
    created_at: str
    updated_at: str


class VerificationProvider(Protocol):
    def verify(self, loop: OpenLoop) -> VerificationResult:
        ...


class ActionExecutor(Protocol):
    def execute(self, action: ActionRecord) -> dict[str, Any]:
        ...

    def confirm(self, action: ActionRecord) -> dict[str, Any]:
        ...


class ShiftStore:
    """SQLite-backed operational memory with evidence and action audit trails."""

    def __init__(self, db_path: str | Path = "shiftrelay.db") -> None:
        self.db_path = str(db_path)
        self._init_db()

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        return conn

    def _init_db(self) -> None:
        with self._connect() as conn:
            conn.executescript(
                """
                PRAGMA foreign_keys = ON;
                CREATE TABLE IF NOT EXISTS shifts (
                    id TEXT PRIMARY KEY,
                    site_id TEXT NOT NULL,
                    worker_id TEXT NOT NULL,
                    shift_type TEXT NOT NULL,
                    status TEXT NOT NULL,
                    started_at TEXT NOT NULL,
                    closed_at TEXT
                );
                CREATE TABLE IF NOT EXISTS loops (
                    id TEXT PRIMARY KEY,
                    site_id TEXT NOT NULL,
                    shift_id TEXT NOT NULL,
                    summary TEXT NOT NULL,
                    category TEXT NOT NULL,
                    subject_key TEXT NOT NULL,
                    evidence_status TEXT NOT NULL,
                    status TEXT NOT NULL,
                    risk TEXT NOT NULL,
                    priority TEXT NOT NULL,
                    owner TEXT,
                    due TEXT,
                    next_action TEXT,
                    last_verification_note TEXT,
                    last_verified_at TEXT,
                    created_by TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS verifications (
                    id TEXT PRIMARY KEY,
                    loop_id TEXT NOT NULL,
                    outcome TEXT NOT NULL,
                    note TEXT NOT NULL,
                    source TEXT NOT NULL,
                    observed_json TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    FOREIGN KEY(loop_id) REFERENCES loops(id)
                );
                CREATE TABLE IF NOT EXISTS actions (
                    id TEXT PRIMARY KEY,
                    loop_id TEXT NOT NULL,
                    action_type TEXT NOT NULL,
                    payload_json TEXT NOT NULL,
                    risk TEXT NOT NULL,
                    status TEXT NOT NULL,
                    approval_required INTEGER NOT NULL,
                    approved_by TEXT,
                    approved_at TEXT,
                    external_ref TEXT,
                    result_json TEXT,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL,
                    FOREIGN KEY(loop_id) REFERENCES loops(id)
                );
                CREATE TABLE IF NOT EXISTS events (
                    seq INTEGER PRIMARY KEY AUTOINCREMENT,
                    site_id TEXT NOT NULL,
                    loop_id TEXT,
                    action_id TEXT,
                    event_type TEXT NOT NULL,
                    payload_json TEXT NOT NULL,
                    created_at TEXT NOT NULL
                );
                """
            )

    def _event(
        self,
        conn: sqlite3.Connection,
        *,
        site_id: str,
        event_type: str,
        payload: dict[str, Any],
        loop_id: str | None = None,
        action_id: str | None = None,
    ) -> None:
        conn.execute(
            "INSERT INTO events(site_id, loop_id, action_id, event_type, payload_json, created_at) VALUES(?,?,?,?,?,?)",
            (site_id, loop_id, action_id, event_type, json.dumps(payload, sort_keys=True), utcnow()),
        )

    def reset(self) -> None:
        with self._connect() as conn:
            conn.executescript("DELETE FROM events; DELETE FROM actions; DELETE FROM verifications; DELETE FROM loops; DELETE FROM shifts;")

    def start_shift(self, site_id: str, worker_id: str, shift_type: str) -> dict[str, Any]:
        shift_id = str(uuid.uuid4())
        now = utcnow()
        result = {
            "shift_id": shift_id,
            "site_id": site_id,
            "worker_id": worker_id,
            "shift_type": shift_type,
            "status": "open",
            "started_at": now,
        }
        with self._connect() as conn:
            conn.execute(
                "INSERT INTO shifts VALUES (?, ?, ?, ?, 'open', ?, NULL)",
                (shift_id, site_id, worker_id, shift_type, now),
            )
            self._event(conn, site_id=site_id, event_type="shift.started", payload=result)
        return result

    def report_exception(
        self,
        *,
        site_id: str,
        shift_id: str,
        created_by: str,
        summary: str,
        category: str,
        subject_key: str,
        evidence_status: EvidenceStatus = EvidenceStatus.REPORTED,
        risk: RiskLevel = RiskLevel.LOW,
        priority: Priority = Priority.MEDIUM,
        owner: str | None = None,
        due: str | None = None,
        next_action: str | None = None,
    ) -> OpenLoop:
        loop_id = str(uuid.uuid4())
        now = utcnow()
        row = OpenLoop(
            id=loop_id,
            site_id=site_id,
            shift_id=shift_id,
            summary=summary,
            category=category,
            subject_key=subject_key,
            evidence_status=evidence_status.value,
            status=LoopStatus.OPEN.value,
            risk=risk.value,
            priority=priority.value,
            owner=owner,
            due=due,
            next_action=next_action,
            last_verification_note=None,
            last_verified_at=None,
            created_by=created_by,
            created_at=now,
            updated_at=now,
        )
        payload = asdict(row)
        with self._connect() as conn:
            conn.execute(
                """INSERT INTO loops
                (id, site_id, shift_id, summary, category, subject_key, evidence_status, status, risk,
                 priority, owner, due, next_action, last_verification_note, last_verified_at,
                 created_by, created_at, updated_at)
                VALUES (:id,:site_id,:shift_id,:summary,:category,:subject_key,:evidence_status,:status,:risk,
                        :priority,:owner,:due,:next_action,:last_verification_note,:last_verified_at,
                        :created_by,:created_at,:updated_at)""",
                payload,
            )
            self._event(conn, site_id=site_id, loop_id=loop_id, event_type="loop.reported", payload=payload)
        return row

    def _get_loop_conn(self, conn: sqlite3.Connection, loop_id: str) -> OpenLoop:
        row = conn.execute("SELECT * FROM loops WHERE id = ?", (loop_id,)).fetchone()
        if row is None:
            raise KeyError(loop_id)
        return OpenLoop(**dict(row))

    def get_loop(self, loop_id: str) -> OpenLoop:
        with self._connect() as conn:
            return self._get_loop_conn(conn, loop_id)

    def update_loop(
        self,
        loop_id: str,
        *,
        status: LoopStatus | None = None,
        owner: str | None = None,
        due: str | None = None,
        next_action: str | None = None,
        evidence_status: EvidenceStatus | None = None,
        priority: Priority | None = None,
    ) -> OpenLoop:
        updates: dict[str, Any] = {"updated_at": utcnow()}
        if status is not None:
            updates["status"] = status.value
        if owner is not None:
            updates["owner"] = owner
        if due is not None:
            updates["due"] = due
        if next_action is not None:
            updates["next_action"] = next_action
        if evidence_status is not None:
            updates["evidence_status"] = evidence_status.value
        if priority is not None:
            updates["priority"] = priority.value
        sets = ", ".join(f"{k} = ?" for k in updates)
        with self._connect() as conn:
            before = self._get_loop_conn(conn, loop_id)
            conn.execute(f"UPDATE loops SET {sets} WHERE id = ?", (*updates.values(), loop_id))
            after = self._get_loop_conn(conn, loop_id)
            self._event(
                conn,
                site_id=after.site_id,
                loop_id=loop_id,
                event_type="loop.updated",
                payload={"before": asdict(before), "after": asdict(after)},
            )
        return after

    def get_open_loops(self, site_id: str) -> list[OpenLoop]:
        priority_order = "CASE priority WHEN 'urgent' THEN 0 WHEN 'high' THEN 1 WHEN 'medium' THEN 2 ELSE 3 END"
        with self._connect() as conn:
            rows = conn.execute(
                f"SELECT * FROM loops WHERE site_id = ? AND status != 'completed' ORDER BY {priority_order}, created_at",
                (site_id,),
            ).fetchall()
        return [OpenLoop(**dict(row)) for row in rows]

    def verify_loop(self, loop_id: str, provider: VerificationProvider) -> tuple[OpenLoop, VerificationResult]:
        with self._connect() as conn:
            loop = self._get_loop_conn(conn, loop_id)
        result = provider.verify(loop)
        now = utcnow()
        if result.outcome == "verified":
            evidence = EvidenceStatus.VERIFIED.value
            status = loop.status
        elif result.outcome == "disputed":
            evidence = EvidenceStatus.DISPUTED.value
            status = LoopStatus.BLOCKED.value
        else:
            evidence = EvidenceStatus.REPORTED.value
            status = LoopStatus.BLOCKED.value if loop.risk == RiskLevel.HIGH.value else loop.status

        with self._connect() as conn:
            conn.execute(
                "INSERT INTO verifications VALUES(?,?,?,?,?,?,?)",
                (str(uuid.uuid4()), loop_id, result.outcome, result.note, result.source, json.dumps(result.observed, sort_keys=True), now),
            )
            conn.execute(
                "UPDATE loops SET evidence_status=?, status=?, last_verification_note=?, last_verified_at=?, updated_at=? WHERE id=?",
                (evidence, status, result.note, now, now, loop_id),
            )
            updated = self._get_loop_conn(conn, loop_id)
            self._event(
                conn,
                site_id=updated.site_id,
                loop_id=loop_id,
                event_type="loop.verification_checked",
                payload={"result": asdict(result), "state": asdict(updated)},
            )
        return updated, result

    def pursue_open_loops(self, site_id: str, provider: VerificationProvider) -> list[dict[str, Any]]:
        outcomes: list[dict[str, Any]] = []
        for loop in self.get_open_loops(site_id):
            if loop.evidence_status == EvidenceStatus.VERIFIED.value:
                continue
            updated, result = self.verify_loop(loop.id, provider)
            outcomes.append({"loop": asdict(updated), "verification": asdict(result)})
        return outcomes

    def close_shift(self, shift_id: str) -> dict[str, Any]:
        now = utcnow()
        with self._connect() as conn:
            conn.execute("UPDATE shifts SET status='closed', closed_at=? WHERE id=?", (now, shift_id))
            row = conn.execute("SELECT * FROM shifts WHERE id=?", (shift_id,)).fetchone()
            if row is None:
                raise KeyError(shift_id)
            result = dict(row)
            self._event(conn, site_id=result["site_id"], event_type="shift.closed", payload=result)
        return result

    def resume_shift(self, site_id: str, worker_id: str, shift_type: str) -> dict[str, Any]:
        shift = self.start_shift(site_id, worker_id, shift_type)
        loops = self.get_open_loops(site_id)
        return {
            "shift": shift,
            "open_loops": [asdict(loop) for loop in loops],
            "handoff_count": len(loops),
        }

    def prepare_action(
        self,
        *,
        loop_id: str,
        action_type: str,
        payload: dict[str, Any],
        risk: RiskLevel = RiskLevel.HIGH,
    ) -> ActionRecord:
        loop = self.get_loop(loop_id)
        if risk == RiskLevel.HIGH and loop.evidence_status != EvidenceStatus.VERIFIED.value:
            raise PermissionError("High-risk action cannot be prepared from unverified operational state")
        now = utcnow()
        action = ActionRecord(
            id=str(uuid.uuid4()),
            loop_id=loop_id,
            action_type=action_type,
            payload=payload,
            risk=risk.value,
            status=ActionStatus.PREPARED.value,
            approval_required=(risk == RiskLevel.HIGH),
            approved_by=None,
            approved_at=None,
            external_ref=None,
            result=None,
            created_at=now,
            updated_at=now,
        )
        with self._connect() as conn:
            conn.execute(
                """INSERT INTO actions
                (id, loop_id, action_type, payload_json, risk, status, approval_required,
                 approved_by, approved_at, external_ref, result_json, created_at, updated_at)
                VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                (
                    action.id, action.loop_id, action.action_type, json.dumps(action.payload, sort_keys=True),
                    action.risk, action.status, int(action.approval_required), action.approved_by,
                    action.approved_at, action.external_ref, None, action.created_at, action.updated_at,
                ),
            )
            self._event(conn, site_id=loop.site_id, loop_id=loop_id, action_id=action.id, event_type="action.prepared", payload=asdict(action))
        return action

    def _action_from_row(self, row: sqlite3.Row) -> ActionRecord:
        return ActionRecord(
            id=row["id"], loop_id=row["loop_id"], action_type=row["action_type"],
            payload=json.loads(row["payload_json"]), risk=row["risk"], status=row["status"],
            approval_required=bool(row["approval_required"]), approved_by=row["approved_by"],
            approved_at=row["approved_at"], external_ref=row["external_ref"],
            result=json.loads(row["result_json"]) if row["result_json"] else None,
            created_at=row["created_at"], updated_at=row["updated_at"],
        )

    def get_action(self, action_id: str) -> ActionRecord:
        with self._connect() as conn:
            row = conn.execute("SELECT * FROM actions WHERE id=?", (action_id,)).fetchone()
        if row is None:
            raise KeyError(action_id)
        return self._action_from_row(row)

    def approve_action(self, action_id: str, approved_by: str) -> ActionRecord:
        now = utcnow()
        with self._connect() as conn:
            row = conn.execute("SELECT * FROM actions WHERE id=?", (action_id,)).fetchone()
            if row is None:
                raise KeyError(action_id)
            current = self._action_from_row(row)
            if current.status != ActionStatus.PREPARED.value:
                raise ValueError(f"Action must be prepared before approval, got {current.status}")
            conn.execute(
                "UPDATE actions SET status=?, approved_by=?, approved_at=?, updated_at=? WHERE id=?",
                (ActionStatus.APPROVED.value, approved_by, now, now, action_id),
            )
            loop = self._get_loop_conn(conn, current.loop_id)
            self._event(conn, site_id=loop.site_id, loop_id=loop.id, action_id=action_id, event_type="action.approved", payload={"approved_by": approved_by})
            row2 = conn.execute("SELECT * FROM actions WHERE id=?", (action_id,)).fetchone()
        return self._action_from_row(row2)

    def execute_action(self, action_id: str, executor: ActionExecutor) -> ActionRecord:
        current = self.get_action(action_id)
        if current.approval_required and current.status != ActionStatus.APPROVED.value:
            raise PermissionError("High-risk action requires explicit human approval before execution")
        if not current.approval_required and current.status != ActionStatus.PREPARED.value:
            raise ValueError(f"Unexpected action status {current.status}")
        result = executor.execute(current)
        now = utcnow()
        external_ref = result.get("external_ref")
        with self._connect() as conn:
            conn.execute(
                "UPDATE actions SET status=?, external_ref=?, result_json=?, updated_at=? WHERE id=?",
                (ActionStatus.EXECUTED.value, external_ref, json.dumps(result, sort_keys=True), now, action_id),
            )
            loop = self._get_loop_conn(conn, current.loop_id)
            conn.execute("UPDATE loops SET status=?, updated_at=? WHERE id=?", (LoopStatus.ACTIONED.value, now, loop.id))
            self._event(conn, site_id=loop.site_id, loop_id=loop.id, action_id=action_id, event_type="action.executed", payload=result)
            row = conn.execute("SELECT * FROM actions WHERE id=?", (action_id,)).fetchone()
        return self._action_from_row(row)

    def confirm_action(self, action_id: str, executor: ActionExecutor) -> ActionRecord:
        current = self.get_action(action_id)
        if current.status != ActionStatus.EXECUTED.value:
            raise ValueError("Only executed actions can be confirmed")
        confirmation = executor.confirm(current)
        now = utcnow()
        merged = dict(current.result or {})
        merged["confirmation"] = confirmation
        status = ActionStatus.CONFIRMED.value if confirmation.get("confirmed") else ActionStatus.FAILED.value
        with self._connect() as conn:
            conn.execute(
                "UPDATE actions SET status=?, result_json=?, updated_at=? WHERE id=?",
                (status, json.dumps(merged, sort_keys=True), now, action_id),
            )
            loop = self._get_loop_conn(conn, current.loop_id)
            if confirmation.get("confirmed"):
                conn.execute("UPDATE loops SET status=?, updated_at=? WHERE id=?", (LoopStatus.COMPLETED.value, now, loop.id))
            self._event(conn, site_id=loop.site_id, loop_id=loop.id, action_id=action_id, event_type="action.confirmed", payload=confirmation)
            row = conn.execute("SELECT * FROM actions WHERE id=?", (action_id,)).fetchone()
        return self._action_from_row(row)

    def list_events(self, site_id: str) -> list[dict[str, Any]]:
        with self._connect() as conn:
            rows = conn.execute("SELECT * FROM events WHERE site_id=? ORDER BY seq", (site_id,)).fetchall()
        result = []
        for row in rows:
            item = dict(row)
            item["payload"] = json.loads(item.pop("payload_json"))
            result.append(item)
        return result

    def snapshot(self, site_id: str) -> dict[str, Any]:
        with self._connect() as conn:
            shifts = [dict(r) for r in conn.execute("SELECT * FROM shifts WHERE site_id=? ORDER BY started_at", (site_id,)).fetchall()]
            loops = [asdict(x) for x in self.get_open_loops(site_id)]
            actions_rows = conn.execute(
                "SELECT a.* FROM actions a JOIN loops l ON a.loop_id=l.id WHERE l.site_id=? ORDER BY a.created_at",
                (site_id,),
            ).fetchall()
        return {
            "site_id": site_id,
            "shifts": shifts,
            "open_loops": loops,
            "actions": [asdict(self._action_from_row(r)) for r in actions_rows],
            "events": self.list_events(site_id),
        }


class DemoVerifier:
    """Deterministic demo evidence provider with optional cross-process persistence.

    When ``evidence_file`` is supplied, every verification reloads the evidence
    snapshot from disk. This lets a separate process simulate an external
    carrier/POS system updating evidence while the MCP server keeps running.
    """

    DEFAULT_STATE = {
        "inventory": {
            "large_cups": {"on_hand_pct": 0.04, "threshold_pct": 0.15, "source": "inventory_demo"}
        },
        "deliveries": {
            "freezer_delivery": {
                "scheduled": True,
                "receipt_scan": None,
                "carrier_exception": None,
                "source": "delivery_demo",
            }
        },
    }

    def __init__(self, evidence_file: str | Path | None = None) -> None:
        self.evidence_file = Path(evidence_file) if evidence_file else None
        self.inventory = json.loads(json.dumps(self.DEFAULT_STATE["inventory"]))
        self.deliveries = json.loads(json.dumps(self.DEFAULT_STATE["deliveries"]))
        if self.evidence_file is not None:
            self.evidence_file.parent.mkdir(parents=True, exist_ok=True)
            if not self.evidence_file.exists():
                self._write_file(self.DEFAULT_STATE)
            self._reload_file()

    def _write_file(self, state: dict[str, Any]) -> None:
        if self.evidence_file is None:
            return
        tmp = self.evidence_file.with_suffix(self.evidence_file.suffix + ".tmp")
        tmp.write_text(json.dumps(state, indent=2, sort_keys=True), encoding="utf-8")
        tmp.replace(self.evidence_file)

    def _reload_file(self) -> None:
        if self.evidence_file is None:
            return
        state = json.loads(self.evidence_file.read_text(encoding="utf-8"))
        self.inventory = state["inventory"]
        self.deliveries = state["deliveries"]

    def reset_external_evidence(self) -> None:
        """Reset persistent demo evidence to the initial external-system state."""
        self.inventory = json.loads(json.dumps(self.DEFAULT_STATE["inventory"]))
        self.deliveries = json.loads(json.dumps(self.DEFAULT_STATE["deliveries"]))
        if self.evidence_file is not None:
            self._write_file({"inventory": self.inventory, "deliveries": self.deliveries})

    def inject_delivery_exception(self, exception: str = "missed_delivery") -> None:
        """Simulate new carrier evidence arriving after the original report."""
        if self.evidence_file is not None:
            self._reload_file()
        self.deliveries["freezer_delivery"]["carrier_exception"] = exception
        if self.evidence_file is not None:
            self._write_file({"inventory": self.inventory, "deliveries": self.deliveries})

    def verify(self, loop: OpenLoop) -> VerificationResult:
        if self.evidence_file is not None:
            self._reload_file()
        if loop.subject_key == "large_cups":
            data = self.inventory["large_cups"]
            verified = data["on_hand_pct"] < data["threshold_pct"]
            return VerificationResult(
                outcome="verified" if verified else "disputed",
                note=(
                    f"Inventory shows {data['on_hand_pct']*100:.0f}% on hand against a "
                    f"{data['threshold_pct']*100:.0f}% morning threshold."
                ),
                source=data["source"],
                observed=data,
            )
        if loop.subject_key == "freezer_delivery":
            data = self.deliveries["freezer_delivery"]
            if data["receipt_scan"]:
                return VerificationResult(
                    outcome="disputed",
                    note="A receipt scan exists; the report of non-arrival conflicts with the delivery system.",
                    source=data["source"],
                    observed=data,
                )
            if data.get("carrier_exception") == "missed_delivery":
                return VerificationResult(
                    outcome="verified",
                    note="Carrier tracking now reports a missed-delivery exception. The non-arrival report is verified.",
                    source=data["source"],
                    observed=data,
                )
            return VerificationResult(
                outcome="inconclusive",
                note="A delivery was scheduled, but there is no receipt scan or carrier exception. Non-arrival is not verified.",
                source=data["source"],
                observed=data,
            )
        return VerificationResult(
            outcome="inconclusive",
            note="No configured evidence source can verify this item.",
            source="none",
            observed={},
        )


class DemoActionExecutor:
    """Deterministic action executor used by the simulation and tests."""

    def __init__(self) -> None:
        self.external_actions: dict[str, dict[str, Any]] = {}

    def execute(self, action: ActionRecord) -> dict[str, Any]:
        if action.action_type == "restock_request":
            ref = f"PO-{action.id[:8].upper()}"
            result = {"external_ref": ref, "accepted": True, "eta": "08:00 tomorrow", **action.payload}
        else:
            ref = f"DEMO-{action.id[:8].upper()}"
            result = {"external_ref": ref, "accepted": True, "action_type": action.action_type, **action.payload}
        self.external_actions[ref] = result
        return result

    def confirm(self, action: ActionRecord) -> dict[str, Any]:
        if action.external_ref and action.external_ref in self.external_actions:
            return {"confirmed": True, "external_ref": action.external_ref, "status": "accepted"}
        return {"confirmed": False, "external_ref": action.external_ref, "status": "not_found"}


def summarize_handoff(loops: Iterable[OpenLoop]) -> str:
    loops = list(loops)
    if not loops:
        return "No open loops carried over from the previous shift."
    lines = [f"{len(loops)} open loop{'s' if len(loops) != 1 else ''} carried over:"]
    for idx, item in enumerate(loops, start=1):
        if item.evidence_status == EvidenceStatus.VERIFIED.value:
            truth = "verified"
        elif item.evidence_status == EvidenceStatus.DISPUTED.value:
            truth = "disputed"
        else:
            truth = "reported, not yet verified"
        owner = item.owner or "unassigned"
        action = item.next_action or "follow up"
        lines.append(f"{idx}. {item.summary} — {truth}; priority: {item.priority}; owner: {owner}; next: {action}.")
    return "\n".join(lines)
