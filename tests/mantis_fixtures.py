from __future__ import annotations

from ad_lit_pipeline.records import RecordEnvelope, record_from_dict
from tests.record_contract_fixtures import valid_record_payloads


VERIFIED_OPEN_CHECKS = [
    "candidate_version_frozen",
    "corpus_snapshot_recorded",
    "as_of_recorded",
    "deterministic_signal_supported",
    "supporting_claims_verified",
    "counterevidence_verified",
    "counterretrieval_complete",
    "synonym_and_indexing_check_complete",
    "adjacent_literature_check_complete",
    "duplicate_check_complete",
    "coverage_adequate_for_rule",
    "uncertainty_recorded",
]


def mantis_record_payloads() -> list[dict[str, object]]:
    """Build a valid, copyright-safe collection with one verified-open gap."""
    payloads = valid_record_payloads()
    gap = next(item for item in payloads if item["record_type"] == "gap_candidate")
    attempt = next(
        item for item in payloads if item["record_type"] == "verification_attempt"
    )
    score = next(item for item in payloads if item["record_type"] == "gap_score")
    attempt.update(
        {
            "attempt_status": "completed",
            "resulting_gap_status": "verified_open",
            "completed_at": "2026-08-27T08:40:00Z",
            "checks": [
                {
                    "check_id": check_id,
                    "status": "passed",
                    "performed_at": "2026-08-27T08:39:00Z",
                    "verifier_id": "fixture-verifier-v1",
                    "evidence_ids": [],
                    "details": f"Synthetic completed check: {check_id}.",
                    "human_review_trigger_ids": [],
                }
                for check_id in VERIFIED_OPEN_CHECKS
            ],
            "unresolved_check_ids": [],
            "decision_rationale": (
                "All required checks passed within the declared synthetic scope."
            ),
        }
    )
    gap["gap_status"] = "verified_open"
    gap["decisive_verification_attempt_id"] = attempt["record_id"]
    gap["state_history"].append(
        {
            "from_gap_status": "verification_in_progress",
            "to_gap_status": "verified_open",
            "transitioned_at": "2026-08-27T08:40:00Z",
            "actor_id": "fixture-verifier-v1",
            "verification_attempt_id": attempt["record_id"],
            "completed_check_ids": VERIFIED_OPEN_CHECKS,
            "reason": "All checks passed within the bounded synthetic scope.",
            "new_candidate_version": False,
        }
    )
    score["candidate_gap_status"] = "verified_open"
    return payloads


def mantis_records() -> tuple[RecordEnvelope, ...]:
    return tuple(record_from_dict(payload) for payload in mantis_record_payloads())
