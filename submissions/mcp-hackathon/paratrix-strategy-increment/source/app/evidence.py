"""Portable evidence with content integrity and deterministic offline verification."""

from app.domain.engine import METHOD_VERSION, evaluate, normalize_curve
from app.storage import digest


class EvidenceError(ValueError):
    pass


def build_evidence(experiment, baseline, candidate, raw_curves=None):
    payload = {
        "schema_version": 1,
        "method_version": experiment["result"]["method_version"],
        "experiment_id": experiment["experiment_id"],
        "created_at": experiment["created_at"],
        "config": experiment["config"],
        "provenance": experiment["provenance"],
        "curves": {"baseline": baseline, "candidate": candidate},
        "result": experiment["result"],
    }
    if raw_curves is not None:
        payload["raw_curves"] = raw_curves
        payload["normalization_version"] = "complete-daily/v1"
    payload["integrity"] = {
        "algorithm": "sha256-canonical-json-v1",
        "payload_sha256": digest(payload),
        "baseline_sha256": digest(baseline),
        "candidate_sha256": digest(candidate),
    }
    return payload


def reproduce(bundle):
    if (
        not isinstance(bundle, dict)
        or type(bundle.get("schema_version")) is not int
        or bundle["schema_version"] != 1
    ):
        raise EvidenceError("Unsupported evidence bundle format")
    if bundle.get("method_version") != METHOD_VERSION:
        raise EvidenceError("Method version mismatch; use the version specified by the evidence bundle")
    if "raw_curves" in bundle and bundle.get("normalization_version") != "complete-daily/v1":
        raise EvidenceError("Unsupported normalization version")
    payload = {key: value for key, value in bundle.items() if key != "integrity"}
    integrity = bundle.get("integrity", {})
    try:
        for field in ("integrity", "curves", "config", "provenance", "result"):
            if not isinstance(bundle.get(field), dict):
                raise EvidenceError("Evidence fields are missing or invalid")
        if "raw_curves" in bundle and not isinstance(bundle["raw_curves"], dict):
            raise EvidenceError("Evidence fields are missing or invalid")
        if (
            integrity["algorithm"] != "sha256-canonical-json-v1"
            or digest(payload) != integrity["payload_sha256"]
        ):
            raise EvidenceError("Evidence payload hash mismatch")
        curves = bundle["curves"]
        for key in ("baseline", "candidate"):
            if digest(curves[key]) != integrity[key + "_sha256"]:
                raise EvidenceError("Input hash mismatch")
            if normalize_curve(curves[key]) != curves[key]:
                raise EvidenceError("Input is not a normalized snapshot")
            if "raw_curves" in bundle and normalize_curve(bundle["raw_curves"][key]) != curves[key]:
                raise EvidenceError("Raw input does not match the normalized snapshot")
        config = bundle["config"]
        # Historical v1 bundles contain Chinese display resources without a locale marker.
        # Select the original presentation while retaining full result equality below.
        recorded_result = bundle["result"]
        display_language = recorded_result.get("display_language", "zh")
        result = evaluate(
            curves["baseline"],
            curves["candidate"],
            start=config["start"],
            end=config["end"],
            criteria=config["criteria"],
            display_language=display_language,
        )
        if "display_language" not in recorded_result:
            result.pop("display_language")
        # Early v1 development bundles predate this additive explanatory field.
        # All original paths, metrics, criteria and statuses must still match.
        if "comparison_facts" not in bundle["result"]:
            result.pop("comparison_facts", None)
        if result != bundle["result"]:
            raise EvidenceError("Reproduced result does not match")
        return {
            "verified": True,
            "experiment_id": bundle["experiment_id"],
            "method_version": METHOD_VERSION,
            "status": result["status"],
            "payload_sha256": integrity["payload_sha256"],
            "note": "Hashes and reproduced results match; this does not authenticate data, authorship, or unseen holdout claims.",
        }
    except (KeyError, TypeError, ValueError) as exc:
        if isinstance(exc, EvidenceError):
            raise
        raise EvidenceError("Evidence fields are missing or invalid") from None
