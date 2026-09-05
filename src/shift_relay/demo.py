"""Deterministic local simulation for SHIFT//RELAY.

SUBMISSION POLICY: this module is NOT evidence of Alexa+ natural-language
reasoning. Its parser is intentionally deterministic for reproducibility. Do
not record the one-utterance -> two-exception scene from this path as if Alexa+
performed the decomposition. Use the live Alexa+ -> official MCP path for that
claim, or label the footage explicitly as a deterministic simulation.
"""
from __future__ import annotations

from dataclasses import asdict
from pathlib import Path
from typing import Any

from .core import (
    DemoActionExecutor,
    DemoVerifier,
    Priority,
    RiskLevel,
    ShiftStore,
    summarize_handoff,
)
from .nlp import decompose_exception_utterance


class DemoScenario:
    SITE_ID = "qsr-17"

    def __init__(self, db_path: str | Path = "shiftrelay-demo.db") -> None:
        self.store = ShiftStore(db_path)
        self.verifier = DemoVerifier()
        self.executor = DemoActionExecutor()
        self.ids: dict[str, str] = {}

    def reset(self) -> dict[str, Any]:
        self.store.reset()
        self.ids = {}
        return {"ok": True, "message": "Demo reset"}

    def night_report(self) -> dict[str, Any]:
        night = self.store.start_shift(self.SITE_ID, "alex", "closing")
        self.ids["night_shift"] = night["shift_id"]
        utterance = "The freezer delivery never arrived, and we're almost out of large cups."
        parsed = decompose_exception_utterance(utterance)
        created = []
        for item in parsed:
            loop = self.store.report_exception(
                site_id=self.SITE_ID, shift_id=night["shift_id"], created_by="alex",
                summary=item.summary, category=item.category, subject_key=item.subject_key,
                risk=RiskLevel(item.risk), priority=Priority(item.priority), owner=item.owner,
                next_action=item.next_action,
            )
            created.append(loop)
            if item.subject_key == "freezer_delivery":
                self.ids["delivery_loop"] = loop.id
            elif item.subject_key == "large_cups":
                self.ids["cups_loop"] = loop.id
        if len(created) != 2:
            raise RuntimeError(f"Demo utterance must decompose into exactly 2 exceptions, got {len(created)}")
        return {
            "simulation_only": True,
            "parser": "deterministic_keyword_simulation",
            "utterance": utterance,
            "spoken": "I captured two separate operational exceptions. I will verify what I can before the next shift.",
            "loops": [asdict(x) for x in created],
        }

    def pursue(self) -> dict[str, Any]:
        results = self.store.pursue_open_loops(self.SITE_ID, self.verifier)
        return {
            "spoken": (
                "I verified the cup shortage from inventory. The freezer delivery is still only reported: "
                "a delivery was scheduled, but there is no receipt scan, so I will not act on that claim yet."
            ),
            "results": results,
        }

    def close_night(self) -> dict[str, Any]:
        result = self.store.close_shift(self.ids["night_shift"])
        return {"spoken": "Closing shift finished. Unresolved work remains durable for the next shift.", "shift": result}

    def morning_resume(self) -> dict[str, Any]:
        result = self.store.resume_shift(self.SITE_ID, "jamie", "opening")
        self.ids["morning_shift"] = result["shift"]["shift_id"]
        loops = self.store.get_open_loops(self.SITE_ID)
        return {
            "spoken": (
                "Two issues carried over. The large-cup shortage is verified and urgent, so I can prepare an action. "
                "The freezer delivery is still unverified, so I will not act on it yet."
            ),
            "handoff": summarize_handoff(loops),
            "state": result,
        }

    def try_unsafe_delivery_action(self) -> dict[str, Any]:
        try:
            self.store.prepare_action(
                loop_id=self.ids["delivery_loop"],
                action_type="supplier_escalation",
                payload={"supplier": "FreezerCo", "message": "Escalate missing delivery"},
                risk=RiskLevel.HIGH,
            )
        except PermissionError as exc:
            return {
                "blocked": True,
                "spoken": "I will not contact the supplier yet. The missing delivery has not been verified.",
                "reason": str(exc),
            }
        raise AssertionError("Unsafe action was unexpectedly prepared")


    def evidence_flip_delivery(self) -> dict[str, Any]:
        """Simulate late external evidence that changes an unresolved claim into a verified fact."""
        self.verifier.inject_delivery_exception("missed_delivery")
        loop, result = self.store.verify_loop(self.ids["delivery_loop"], self.verifier)
        return {
            "spoken": (
                "New carrier evidence arrived. The freezer non-arrival is now verified. "
                "I can prepare supplier follow-up, but execution still requires approval."
            ),
            "loop": asdict(loop),
            "verification": asdict(result),
        }

    def resolve_verified_delivery(self, approved_by: str = "jamie") -> dict[str, Any]:
        action = self.store.prepare_action(
            loop_id=self.ids["delivery_loop"],
            action_type="supplier_followup",
            payload={"supplier": "FreezerCo", "reason": "verified missed delivery"},
            risk=RiskLevel.HIGH,
        )
        approved = self.store.approve_action(action.id, approved_by)
        executed = self.store.execute_action(approved.id, self.executor)
        confirmed = self.store.confirm_action(executed.id, self.executor)
        return {
            "spoken": (
                "Because the evidence changed, my decision changed. Supplier follow-up was approved, "
                f"executed, and confirmed as {confirmed.external_ref}."
            ),
            "action": asdict(confirmed),
        }

    def prepare_restock(self) -> dict[str, Any]:
        action = self.store.prepare_action(
            loop_id=self.ids["cups_loop"],
            action_type="restock_request",
            payload={"sku": "LARGE-CUP", "quantity_cases": 10, "site_id": self.SITE_ID},
            risk=RiskLevel.HIGH,
        )
        self.ids["restock_action"] = action.id
        return {
            "spoken": "Large cups are verified below threshold. I prepared a restock request for 10 cases. Approve?",
            "action": asdict(action),
        }

    def approve_restock(self, approved_by: str = "jamie") -> dict[str, Any]:
        action = self.store.approve_action(self.ids["restock_action"], approved_by)
        return {"spoken": f"Approval recorded from {approved_by}.", "action": asdict(action)}

    def execute_restock(self) -> dict[str, Any]:
        action = self.store.execute_action(self.ids["restock_action"], self.executor)
        return {"spoken": f"Restock request submitted. Confirmation {action.external_ref}.", "action": asdict(action)}

    def confirm_restock(self) -> dict[str, Any]:
        action = self.store.confirm_action(self.ids["restock_action"], self.executor)
        return {
            "spoken": f"The order system confirmed {action.external_ref}. The cup issue is now closed.",
            "action": asdict(action),
        }

    def snapshot(self) -> dict[str, Any]:
        return self.store.snapshot(self.SITE_ID)

    def run_full(self) -> dict[str, Any]:
        self.reset()
        steps = [
            ("night_report", self.night_report()),
            ("verification_loop", self.pursue()),
            ("close_night", self.close_night()),
            ("morning_resume", self.morning_resume()),
            ("safe_refusal", self.try_unsafe_delivery_action()),
            ("evidence_flip", self.evidence_flip_delivery()),
            ("delivery_resolution", self.resolve_verified_delivery()),
            ("prepare_restock", self.prepare_restock()),
            ("approve_restock", self.approve_restock()),
            ("execute_restock", self.execute_restock()),
            ("closed_loop_confirmation", self.confirm_restock()),
        ]
        return {"steps": [{"name": n, **payload} for n, payload in steps], "snapshot": self.snapshot()}
