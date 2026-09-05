from pathlib import Path
import tempfile

import pytest

from shift_relay.core import (
    DemoActionExecutor,
    DemoVerifier,
    EvidenceStatus,
    LoopStatus,
    Priority,
    RiskLevel,
    ShiftStore,
    summarize_handoff,
)
from shift_relay.demo import DemoScenario


def make_store(td: str) -> ShiftStore:
    return ShiftStore(Path(td) / "test.db")


def test_cross_shift_resume_preserves_only_unresolved_loops():
    with tempfile.TemporaryDirectory() as td:
        store = make_store(td)
        night = store.start_shift("store-17", "alex", "closing")
        delivery = store.report_exception(
            site_id="store-17", shift_id=night["shift_id"], created_by="alex",
            summary="Freezer delivery may not have arrived", category="delivery", subject_key="freezer_delivery",
            owner="manager", next_action="Confirm delivery status with supplier",
        )
        cups = store.report_exception(
            site_id="store-17", shift_id=night["shift_id"], created_by="alex",
            summary="Large cups are almost out", category="inventory", subject_key="large_cups",
            owner="morning lead", next_action="Check stock and prepare restock request",
        )
        store.update_loop(cups.id, status=LoopStatus.COMPLETED)
        store.close_shift(night["shift_id"])
        morning = store.resume_shift("store-17", "jamie", "opening")
        assert morning["handoff_count"] == 1
        assert morning["open_loops"][0]["id"] == delivery.id


def test_reported_fact_is_not_silently_upgraded_to_verified():
    with tempfile.TemporaryDirectory() as td:
        store = make_store(td)
        shift = store.start_shift("hotel-2", "sam", "night")
        item = store.report_exception(
            site_id="hotel-2", shift_id=shift["shift_id"], created_by="sam",
            summary="Guest says elevator made a grinding noise", category="maintenance", subject_key="elevator_noise",
        )
        assert item.evidence_status == "reported"
        assert "not yet verified" in summarize_handoff([item])


def test_verification_loop_distinguishes_verified_and_inconclusive():
    with tempfile.TemporaryDirectory() as td:
        store = make_store(td)
        verifier = DemoVerifier()
        shift = store.start_shift("qsr-17", "alex", "closing")
        delivery = store.report_exception(
            site_id="qsr-17", shift_id=shift["shift_id"], created_by="alex", summary="Delivery missing",
            category="delivery", subject_key="freezer_delivery", risk=RiskLevel.HIGH,
        )
        cups = store.report_exception(
            site_id="qsr-17", shift_id=shift["shift_id"], created_by="alex", summary="Cups low",
            category="inventory", subject_key="large_cups", risk=RiskLevel.HIGH, priority=Priority.URGENT,
        )
        delivery_after, delivery_result = store.verify_loop(delivery.id, verifier)
        cups_after, cups_result = store.verify_loop(cups.id, verifier)
        assert delivery_result.outcome == "inconclusive"
        assert delivery_after.evidence_status == EvidenceStatus.REPORTED.value
        assert cups_result.outcome == "verified"
        assert cups_after.evidence_status == EvidenceStatus.VERIFIED.value


def test_high_risk_action_cannot_be_prepared_from_unverified_state():
    with tempfile.TemporaryDirectory() as td:
        store = make_store(td)
        shift = store.start_shift("qsr-17", "alex", "closing")
        loop = store.report_exception(
            site_id="qsr-17", shift_id=shift["shift_id"], created_by="alex", summary="Delivery missing",
            category="delivery", subject_key="freezer_delivery", risk=RiskLevel.HIGH,
        )
        with pytest.raises(PermissionError):
            store.prepare_action(loop_id=loop.id, action_type="supplier_escalation", payload={}, risk=RiskLevel.HIGH)


def test_high_risk_action_cannot_execute_without_approval():
    with tempfile.TemporaryDirectory() as td:
        store = make_store(td)
        verifier = DemoVerifier()
        executor = DemoActionExecutor()
        shift = store.start_shift("qsr-17", "alex", "closing")
        loop = store.report_exception(
            site_id="qsr-17", shift_id=shift["shift_id"], created_by="alex", summary="Cups low",
            category="inventory", subject_key="large_cups", risk=RiskLevel.HIGH,
        )
        store.verify_loop(loop.id, verifier)
        action = store.prepare_action(loop_id=loop.id, action_type="restock_request", payload={"quantity_cases": 10}, risk=RiskLevel.HIGH)
        with pytest.raises(PermissionError):
            store.execute_action(action.id, executor)


def test_closed_loop_action_requires_approval_then_external_confirmation():
    with tempfile.TemporaryDirectory() as td:
        store = make_store(td)
        verifier = DemoVerifier()
        executor = DemoActionExecutor()
        shift = store.start_shift("qsr-17", "alex", "closing")
        loop = store.report_exception(
            site_id="qsr-17", shift_id=shift["shift_id"], created_by="alex", summary="Cups low",
            category="inventory", subject_key="large_cups", risk=RiskLevel.HIGH,
        )
        store.verify_loop(loop.id, verifier)
        action = store.prepare_action(loop_id=loop.id, action_type="restock_request", payload={"quantity_cases": 10}, risk=RiskLevel.HIGH)
        store.approve_action(action.id, "jamie")
        executed = store.execute_action(action.id, executor)
        assert executed.status == "executed"
        assert store.get_loop(loop.id).status == "actioned"
        confirmed = store.confirm_action(action.id, executor)
        assert confirmed.status == "confirmed"
        assert store.get_loop(loop.id).status == "completed"


def test_priority_orders_urgent_before_high():
    with tempfile.TemporaryDirectory() as td:
        store = make_store(td)
        shift = store.start_shift("qsr-17", "alex", "closing")
        store.report_exception(site_id="qsr-17", shift_id=shift["shift_id"], created_by="alex", summary="High", category="x", subject_key="x", priority=Priority.HIGH)
        store.report_exception(site_id="qsr-17", shift_id=shift["shift_id"], created_by="alex", summary="Urgent", category="y", subject_key="y", priority=Priority.URGENT)
        loops = store.get_open_loops("qsr-17")
        assert loops[0].summary == "Urgent"


def test_full_demo_contains_safe_refusal_and_closed_loop_confirmation():
    with tempfile.TemporaryDirectory() as td:
        demo = DemoScenario(Path(td) / "demo.db")
        result = demo.run_full()
        by_name = {x["name"]: x for x in result["steps"]}
        assert by_name["safe_refusal"]["blocked"] is True
        assert "will not" in by_name["safe_refusal"]["spoken"].lower()
        assert by_name["closed_loop_confirmation"]["action"]["status"] == "confirmed"
        assert len(result["snapshot"]["open_loops"]) == 0  # evidence flip resolves delivery; cups is also closed


def test_demo_utterance_decomposes_into_two_typed_exceptions():
    from shift_relay.nlp import decompose_exception_utterance
    items = decompose_exception_utterance("The freezer delivery never arrived, and we're almost out of large cups.")
    assert len(items) == 2
    assert {x.subject_key for x in items} == {"freezer_delivery", "large_cups"}
    by_key = {x.subject_key: x for x in items}
    assert by_key["freezer_delivery"].priority == "high"
    assert by_key["large_cups"].priority == "urgent"


def test_evidence_flip_changes_decision_and_allows_action():
    with tempfile.TemporaryDirectory() as td:
        store = make_store(td)
        verifier = DemoVerifier()
        executor = DemoActionExecutor()
        shift = store.start_shift("qsr-17", "alex", "closing")
        loop = store.report_exception(
            site_id="qsr-17", shift_id=shift["shift_id"], created_by="alex", summary="Delivery missing",
            category="delivery", subject_key="freezer_delivery", risk=RiskLevel.HIGH,
        )
        before, result1 = store.verify_loop(loop.id, verifier)
        assert result1.outcome == "inconclusive"
        assert before.evidence_status == EvidenceStatus.REPORTED.value
        with pytest.raises(PermissionError):
            store.prepare_action(loop_id=loop.id, action_type="supplier_followup", payload={}, risk=RiskLevel.HIGH)

        verifier.inject_delivery_exception("missed_delivery")
        after, result2 = store.verify_loop(loop.id, verifier)
        assert result2.outcome == "verified"
        assert after.evidence_status == EvidenceStatus.VERIFIED.value

        action = store.prepare_action(loop_id=loop.id, action_type="supplier_followup", payload={"supplier": "FreezerCo"}, risk=RiskLevel.HIGH)
        store.approve_action(action.id, "jamie")
        store.execute_action(action.id, executor)
        confirmed = store.confirm_action(action.id, executor)
        assert confirmed.status == "confirmed"
        assert store.get_loop(loop.id).status == LoopStatus.COMPLETED.value


def test_full_demo_contains_live_evidence_flip_after_refusal():
    with tempfile.TemporaryDirectory() as td:
        demo = DemoScenario(Path(td) / "demo.db")
        result = demo.run_full()
        by_name = {x["name"]: x for x in result["steps"]}
        assert by_name["safe_refusal"]["blocked"] is True
        assert by_name["evidence_flip"]["verification"]["outcome"] == "verified"
        assert by_name["delivery_resolution"]["action"]["status"] == "confirmed"


def test_external_evidence_persists_across_verifier_process_boundary(tmp_path):
    from shift_relay.core import DemoVerifier, Priority, RiskLevel, ShiftStore

    evidence_file = tmp_path / "evidence.json"
    db_file = tmp_path / "state.db"
    store = ShiftStore(db_file)
    verifier_server = DemoVerifier(evidence_file)
    verifier_external = DemoVerifier(evidence_file)

    shift = store.start_shift("qsr-17", "alex", "closing")
    loop = store.report_exception(
        site_id="qsr-17",
        shift_id=shift["shift_id"],
        created_by="alex",
        summary="The chilled-goods truck seems to have missed its drop.",
        category="delivery",
        subject_key="freezer_delivery",
        risk=RiskLevel.HIGH,
        priority=Priority.HIGH,
    )

    _, before = store.verify_loop(loop.id, verifier_server)
    assert before.outcome == "inconclusive"

    # Simulates a distinct external process updating the shared provider evidence.
    verifier_external.inject_delivery_exception("missed_delivery")

    updated, after = store.verify_loop(loop.id, verifier_server)
    assert after.outcome == "verified"
    assert updated.id == loop.id
    assert updated.evidence_status == "verified"
