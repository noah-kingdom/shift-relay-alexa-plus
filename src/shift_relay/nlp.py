from __future__ import annotations

from dataclasses import dataclass, asdict

from .core import Priority, RiskLevel


@dataclass(frozen=True)
class ParsedException:
    summary: str
    category: str
    subject_key: str
    risk: str
    priority: str
    owner: str
    next_action: str


# SIMULATION-ONLY deterministic parser. DO NOT use this module as evidence of Alexa+ NLU.
# In the real Alexa+ MCP path, Alexa+ reasoning must decide to call report_exception
# once per distinct issue. This parser exists only so the public web simulation is
# reproducible without an external model/API. Submission video must identify this
# path as deterministic simulation or, preferably, use the live Alexa+ MCP path.
def decompose_exception_utterance(text: str) -> list[ParsedException]:
    normalized = " ".join(text.lower().replace("’", "'").split())
    results: list[ParsedException] = []

    delivery_terms = ("freezer delivery", "delivery never arrived", "delivery didn't arrive", "delivery did not arrive")
    if any(term in normalized for term in delivery_terms):
        results.append(
            ParsedException(
                summary="Freezer delivery was reported missing",
                category="delivery",
                subject_key="freezer_delivery",
                risk=RiskLevel.HIGH.value,
                priority=Priority.HIGH.value,
                owner="morning manager",
                next_action="Verify receipt status before any supplier action",
            )
        )

    cup_terms = ("large cups", "cups are almost out", "almost out of large cups", "low on large cups")
    if any(term in normalized for term in cup_terms):
        results.append(
            ParsedException(
                summary="Large cups are almost out",
                category="inventory",
                subject_key="large_cups",
                risk=RiskLevel.HIGH.value,
                priority=Priority.URGENT.value,
                owner="morning lead",
                next_action="Verify inventory and prepare restock if confirmed",
            )
        )

    if not results:
        results.append(
            ParsedException(
                summary=text.strip(),
                category="general",
                subject_key="unclassified",
                risk=RiskLevel.LOW.value,
                priority=Priority.MEDIUM.value,
                owner="shift lead",
                next_action="Review and classify the report",
            )
        )
    return results
