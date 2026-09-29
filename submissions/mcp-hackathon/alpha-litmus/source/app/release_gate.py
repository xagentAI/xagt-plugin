"""Release-gate projection over a verified authoritative Report.

Reuses the existing analysis and certificate engine. This module performs no
quantitative computation and must not duplicate calculations from app.lab.
Every projection first validates its source with the existing
app.certificates.verify_report and fails closed on any invalid certificate.
Verification replays the bounded reference/reconciliation calculations, so a
release-gate call costs roughly one challenge plus one verification replay.
"""

from typing import Literal

from app.contracts import (
    ChallengeRequest,
    ReleaseAction,
    ReleaseDecision,
    ReleaseGateResult,
    Report,
    Verdict,
)

RELEASE_SCHEMA_VERSION: Literal["alphalitmus-release-gate-1"] = "alphalitmus-release-gate-1"

RELEASE_DISCLAIMER: Literal[
    "This result is not financial advice and is not deployment approval. "
    "SURVIVED_BOUNDED_TESTS means only survival of the stated bounded tests."
] = (
    "This result is not financial advice and is not deployment approval. "
    "SURVIVED_BOUNDED_TESTS means only survival of the stated bounded tests."
)

DECISION_FOR_VERDICT: dict[Verdict, ReleaseDecision] = {
    "FRAGILE": "BLOCK_DEPLOYMENT",
    "INCONSISTENT": "BLOCK_DEPLOYMENT",
    "UNPROVEN": "INSUFFICIENT_EVIDENCE",
    "SURVIVED_TESTS": "SURVIVED_BOUNDED_TESTS",
}

ACTION_FOR_DECISION: dict[ReleaseDecision, ReleaseAction] = {
    "BLOCK_DEPLOYMENT": "DO_NOT_DEPLOY",
    "INSUFFICIENT_EVIDENCE": "COLLECT_MORE_EVIDENCE",
    "SURVIVED_BOUNDED_TESTS": "CONTINUE_PAPER_VALIDATION",
}


def decision_for_verdict(verdict: Verdict) -> ReleaseDecision:
    return DECISION_FOR_VERDICT[verdict]


def action_for_decision(decision: ReleaseDecision) -> ReleaseAction:
    return ACTION_FOR_DECISION[decision]


def project(report: Report) -> ReleaseGateResult:
    """Convert a verified authoritative Report into a machine-actionable result.

    Reads the Report, never mutates it, performs no LLM call, and introduces
    no parallel analysis implementation. Fails closed with a sanitized
    REPORT_VERIFICATION_FAILED error unless the existing certificate verifier
    accepts the source report.
    """
    # Deferred imports avoid a top-level cycle (app.transport imports this module).
    from app.certificates import verify_report
    from app.transport import TransportError

    # Revalidate at the trust boundary without mutating the caller's instance.
    checked = Report.model_validate(report.model_dump(mode="python"))
    if not verify_report(checked).valid:
        raise TransportError(500, "REPORT_VERIFICATION_FAILED")
    decision = decision_for_verdict(checked.verdict)
    return ReleaseGateResult(
        schema_version=RELEASE_SCHEMA_VERSION,
        decision=decision,
        recommended_action=action_for_decision(decision),
        source_verdict=checked.verdict,
        evidence_classification=checked.evidence_classification,
        reason_codes=sorted(checked.reason_codes),
        observed_failures=sorted(checked.observed_failures),
        unavailable_tests=sorted(checked.unavailable_tests),
        report_id=checked.report_id,
        canonical_report_hash=checked.canonical_report_hash,
        no_execution=True,
        profitability_claimed=False,
        source_report_verified=True,
        report=checked,
        disclaimer=RELEASE_DISCLAIMER,
    )


def evaluate(request: ChallengeRequest) -> ReleaseGateResult:
    """Run the existing analysis engine, then apply the pure projection."""
    from app.lab import challenge

    # Revalidate even model_construct/model_copy instances at the trust boundary.
    checked = ChallengeRequest.model_validate(request.model_dump(mode="python"))
    return project(challenge(checked))
