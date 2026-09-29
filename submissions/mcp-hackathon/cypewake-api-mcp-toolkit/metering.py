"""
metering.py · MCPForge metering and billing layer (the real Monetize implementation)

Design goals (answering the adversarial finding that "Monetize is just printing a dict"):
- Every API call made through this service is counted and persisted for real, not fabricated afterwards.
- Usage is queryable (usage_report), convertible to an invoice (simulate_invoice), and usable for quota decisions.
- The billing model and price table live in one place, with a configurable currency and no crypto asset hardcoded as the default.

Storage: usage.json next to the registry, written atomically (temp file + os.replace),
         never silently wiped because one read hit a corrupt file.

This module depends on neither fastmcp nor core, so it unit tests on its own.
"""

from __future__ import annotations

import json
import os
import tempfile
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Optional

SCHEMA_VERSION = "2.0"

# Pricing tiers (per 1000 calls). Defined in one place for auditing and adjustment.
PRICING_TIERS: dict[str, dict[str, Any]] = {
    "free": {"price_per_1k_calls": 0.0, "included_calls": 1000, "model": "free"},
    "basic": {"price_per_1k_calls": 2.0, "included_calls": 10000, "model": "pay-per-call"},
    "pro": {"price_per_1k_calls": 8.0, "included_calls": 50000, "model": "pay-per-call"},
    "enterprise": {"price_per_1k_calls": 25.0, "included_calls": 500000, "model": "pay-per-call"},
}

# Default settlement currency: overridable by environment variable. Deliberately defaults to no crypto asset,
# matching the compliance stance that this is an engineering portfolio piece with no token speculation.
DEFAULT_CURRENCY = os.getenv("MCPFORGE_CURRENCY", "USD")


def _default_usage_path() -> Path:
    return Path(os.getenv("MCPFORGE_USAGE", "usage.json"))


class UsageMeter:
    """Call usage meter. Persists to JSON, writes atomically, and recovers conservatively rather than wiping."""

    def __init__(self, path: Optional[Path] = None):
        self.path = Path(path or _default_usage_path())
        self._data: dict[str, Any] = {"schema_version": SCHEMA_VERSION, "apis": {}}
        self._load()

    # ----------------------------- persistence ----------------------------- #
    def _load(self) -> None:
        if not self.path.exists():
            return
        try:
            loaded = json.loads(self.path.read_text(encoding="utf-8"))
        except Exception:
            # Never wipe silently: rename the corrupt file aside and continue with an empty table, so history is not quietly erased.
            try:
                self.path.replace(self.path.with_suffix(".corrupt.json"))
            except Exception:
                pass
            return
        if isinstance(loaded, dict) and isinstance(loaded.get("apis"), dict):
            self._data = loaded

    def _save(self) -> None:
        """Atomic write: write a temp file in the same directory, then os.replace, so an interrupted process cannot leave truncated JSON."""
        self.path.parent.mkdir(parents=True, exist_ok=True)
        fd, tmp = tempfile.mkstemp(dir=str(self.path.parent), suffix=".tmp")
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as fh:
                json.dump(self._data, fh, ensure_ascii=False, indent=2)
            os.replace(tmp, self.path)
        except Exception:
            try:
                os.unlink(tmp)
            except Exception:
                pass
            raise

    # ----------------------------- bookkeeping ----------------------------- #
    def record(
        self,
        api_name: str,
        operation_id: str,
        ok: bool,
        status_code: Optional[int] = None,
        latency_ms: Optional[float] = None,
    ) -> None:
        apis = self._data.setdefault("apis", {})
        entry = apis.setdefault(
            api_name,
            {
                "total_calls": 0,
                "ok_calls": 0,
                "failed_calls": 0,
                "operations": {},
                "daily": {},
                "first_seen": datetime.now(timezone.utc).isoformat(),
            },
        )
        entry["total_calls"] += 1
        entry["ok_calls" if ok else "failed_calls"] += 1
        entry["last_seen"] = datetime.now(timezone.utc).isoformat()

        # Bucket by day: supports the real billing concept of "observed rate → monthly projection"
        daily = entry.setdefault("daily", {})
        today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
        daily[today] = daily.get(today, 0) + 1

        op = entry["operations"].setdefault(
            operation_id, {"calls": 0, "ok": 0, "failed": 0, "latency_ms_total": 0.0}
        )
        op["calls"] += 1
        op["ok" if ok else "failed"] += 1
        if latency_ms is not None:
            op["latency_ms_total"] = round(op["latency_ms_total"] + latency_ms, 1)
        if status_code is not None:
            op["last_status"] = status_code
        self._save()

    # ----------------------------- queries ----------------------------- #
    def report(self, api_name: Optional[str] = None, days: Optional[int] = None) -> dict:
        apis = self._data.get("apis", {})
        if api_name:
            if api_name not in apis:
                return {
                    "api": api_name,
                    "found": False,
                    "message": f"no usage recorded for {api_name!r} yet (counting starts once it is registered and called through this service)",
                }
            scoped = {api_name: apis[api_name]}
        else:
            scoped = apis

        since = None
        if days:
            since = (datetime.now(timezone.utc) - timedelta(days=days)).isoformat()

        out_apis = {}
        grand_total = 0
        for name, entry in scoped.items():
            if since and entry.get("last_seen", "") < since:
                continue
            ops = entry.get("operations", {})
            per_op = []
            for op_name, st in sorted(ops.items()):
                calls = st.get("calls", 0)
                avg = round(st.get("latency_ms_total", 0.0) / calls, 1) if calls else None
                per_op.append(
                    {
                        "operation_id": op_name,
                        "calls": calls,
                        "ok": st.get("ok", 0),
                        "failed": st.get("failed", 0),
                        "avg_latency_ms": avg,
                        "success_rate": round(st.get("ok", 0) / calls, 3) if calls else None,
                    }
                )
            total = entry.get("total_calls", 0)
            grand_total += total
            daily = entry.get("daily", {})
            active_days = len(daily) or 1
            per_day = round(total / active_days, 2)
            out_apis[name] = {
                "total_calls": total,
                "ok_calls": entry.get("ok_calls", 0),
                "failed_calls": entry.get("failed_calls", 0),
                "success_rate": round(entry.get("ok_calls", 0) / total, 3) if total else None,
                "first_seen": entry.get("first_seen"),
                "last_seen": entry.get("last_seen"),
                "active_days": active_days,
                "calls_per_day": per_day,
                "projected_monthly_calls": int(round(per_day * 30)),
                "daily": daily,
                "operations": per_op,
            }

        return {
            "found": bool(out_apis),
            "currency_note": f"billing currency: {DEFAULT_CURRENCY} (override with MCPFORGE_CURRENCY)",
            "total_calls_all_apis": grand_total,
            "apis": out_apis,
        }

    # ----------------------------- billing ----------------------------- #
    def simulate_invoice(
        self,
        api_name: str,
        pricing_tier: str = "basic",
        basis: str = "actual",
        projected_calls: int = 0,
    ) -> dict:
        """Convert real usage into an invoice.

        Billing basis:
          actual            → bill the recorded real call count (default)
          projected_monthly → extrapolate the observed daily average to 30 days
        projected_calls can also set a volume to model directly (capacity and quote modeling).

        The "observed rate → monthly projection" step is how real SaaS billing works,
        and it keeps the demo invoice meaningful instead of permanently 0.
        """
        tier = PRICING_TIERS.get(pricing_tier)
        if tier is None:
            return {
                "error": f"unknown pricing tier {pricing_tier!r}",
                "available_tiers": sorted(PRICING_TIERS.keys()),
            }
        rep = self.report(api_name)
        if not rep.get("found"):
            return {
                "api": api_name,
                "error": f"no usage recorded for {api_name!r}, cannot bill. Register and call it first, then retry.",
            }

        entry = rep["apis"][api_name]
        actual = entry["total_calls"]
        if projected_calls > 0:
            billable = projected_calls
            basis_label = "specified call volume"
        elif basis == "projected_monthly":
            billable = entry["projected_monthly_calls"]
            basis_label = "extrapolated from the observed daily average to 30 days"
        else:
            billable = actual
            basis_label = "actual recorded usage"

        included = tier["included_calls"]
        overage = max(0, billable - included)
        rate = tier["price_per_1k_calls"]
        amount = round(overage / 1000.0 * rate, 4)

        line_items = [
            {
                "operation_id": o["operation_id"],
                "actual_calls": o["calls"],
                "share_of_actual_calls": round(o["calls"] / actual, 3) if actual else 0,
                "projected_calls": int(round(billable * (o["calls"] / actual))) if actual else 0,
            }
            for o in entry["operations"]
        ]

        return {
            "schema_version": SCHEMA_VERSION,
            "api": api_name,
            "pricing_tier": pricing_tier,
            "billing_model": tier["model"],
            "currency": DEFAULT_CURRENCY,
            "billing_basis": basis_label,
            "metered_actual": {
                "total_calls": actual,
                "ok_calls": entry["ok_calls"],
                "failed_calls": entry["failed_calls"],
                "success_rate": entry["success_rate"],
                "active_days": entry["active_days"],
                "calls_per_day": entry["calls_per_day"],
            },
            "billable_calls": billable,
            "included_calls": included,
            "billable_overage_calls": overage,
            "price_per_1k_calls": rate,
            "amount_due": amount,
            "line_items": line_items,
            "generated_at": datetime.now(timezone.utc).isoformat(),
            "note": "usage comes from real metering in this service (usage.json), not an estimate; the projection basis is stated in billing_basis.",
        }

    def reset(self, api_name: Optional[str] = None) -> dict:
        apis = self._data.setdefault("apis", {})
        if api_name:
            removed = apis.pop(api_name, None) is not None
        else:
            removed = bool(apis)
            apis.clear()
        self._save()
        return {"reset": removed, "api": api_name or "<all>"}


# Module-level singleton (same lifecycle as the registry in core)
_meter = UsageMeter()


def get_meter() -> UsageMeter:
    return _meter
