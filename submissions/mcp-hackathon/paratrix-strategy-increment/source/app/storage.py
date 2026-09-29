"""Pure record serialization, integrity and transactional classification helpers."""

import hashlib
import json
from copy import deepcopy
from datetime import datetime, timezone


def canonical(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False)


def digest(value):
    return hashlib.sha256(canonical(value).encode()).hexdigest()


def now():
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


class QuotaExceeded(Exception):
    pass


class IntegrityError(Exception):
    pass


class StorageUnavailable(Exception):
    pass


def finalize_experiment(record, history):
    """Apply history-dependent provenance while holding the insertion transaction."""
    record = deepcopy(record)
    start = datetime.fromisoformat(record["config"]["start"].replace("Z", "+00:00"))
    end = datetime.fromisoformat(record["config"]["end"].replace("Z", "+00:00"))
    reasons = record["provenance"]["exploration_reasons"]
    if any(
        datetime.fromisoformat(item["config"]["start"].replace("Z", "+00:00")) < end
        and start < datetime.fromisoformat(item["config"]["end"].replace("Z", "+00:00"))
        for item in history
    ):
        reason = "This session has an experiment over an overlapping interval; it cannot be relabeled as an unseen holdout."
        if reason not in reasons:
            reasons.append(reason)
    record["provenance"]["effective_mode"] = "historical_exploration" if reasons else "declared_holdout"
    return record
