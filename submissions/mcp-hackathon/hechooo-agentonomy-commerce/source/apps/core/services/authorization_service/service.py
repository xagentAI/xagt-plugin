import json
import os
from datetime import datetime, timedelta
from decimal import Decimal, InvalidOperation
from pathlib import Path
from uuid import uuid4

from services.authorization_service.schemas import (
    AuthorizationCheckResult,
    BudgetAuthorization,
    CheckAuthorizationRequest,
    CreateAuthorizationRequest,
    SpendAuthorizationRequest,
)


class AuthorizationService:
    """Owns budget authorization records and checks."""

    def __init__(self) -> None:
        default_file = Path(__file__).resolve().parent / "authorizations.jsonl"
        self.storage_file = Path(os.getenv("AUTHORIZATION_SESSION_FILE", str(default_file)))

    def create_authorization(self, request: CreateAuthorizationRequest) -> BudgetAuthorization:
        now = self._utc_now()
        max_amount = self._parse_amount(request.max_amount_usdc)
        expires_at = now + timedelta(minutes=max(1, request.expires_in_minutes))
        authorization = BudgetAuthorization(
            authorization_id=f"auth_{uuid4().hex[:12]}",
            user_id=request.user_id,
            agent_id=request.agent_id,
            max_amount_usdc=self._format_amount(max_amount),
            spent_amount_usdc="0",
            remaining_amount_usdc=self._format_amount(max_amount),
            status="active",
            expires_at=self._format_time(expires_at),
            created_at=self._format_time(now),
            updated_at=self._format_time(now),
            event_log=[
                {
                    "event": "created",
                    "amount_usdc": self._format_amount(max_amount),
                    "created_at": self._format_time(now),
                }
            ],
        )
        self._save_record(authorization)
        return authorization

    def get_authorization(self, authorization_id: str) -> BudgetAuthorization | None:
        record = self._load_latest().get(authorization_id)
        if not record:
            return None
        return self._normalize_status(record)

    def check_authorization(
        self,
        authorization_id: str,
        request: CheckAuthorizationRequest,
    ) -> AuthorizationCheckResult | None:
        authorization = self.get_authorization(authorization_id)
        if authorization is None:
            return None

        amount = self._parse_amount(request.amount_usdc)
        remaining = self._parse_amount(authorization.remaining_amount_usdc)
        approved = authorization.status == "active" and amount <= remaining
        if authorization.status != "active":
            reason = f"authorization is {authorization.status}"
        elif amount > remaining:
            reason = "amount exceeds remaining budget"
        else:
            reason = "approved"

        return AuthorizationCheckResult(
            authorization_id=authorization.authorization_id,
            approved=approved,
            status=authorization.status,
            reason=reason,
            amount_usdc=self._format_amount(amount),
            remaining_amount_usdc=authorization.remaining_amount_usdc,
        )

    def spend_authorization(
        self,
        authorization_id: str,
        request: SpendAuthorizationRequest,
    ) -> AuthorizationCheckResult | None:
        authorization = self.get_authorization(authorization_id)
        if authorization is None:
            return None

        check = self.check_authorization(
            authorization_id,
            CheckAuthorizationRequest(amount_usdc=request.amount_usdc),
        )
        if check is None or not check.approved:
            return check

        amount = self._parse_amount(request.amount_usdc)
        spent = self._parse_amount(authorization.spent_amount_usdc) + amount
        max_amount = self._parse_amount(authorization.max_amount_usdc)
        remaining = max_amount - spent
        status = "exhausted" if remaining <= Decimal("0") else "active"
        now = self._utc_now()
        updated = authorization.model_copy(
            update={
                "spent_amount_usdc": self._format_amount(spent),
                "remaining_amount_usdc": self._format_amount(max(remaining, Decimal("0"))),
                "status": status,
                "updated_at": self._format_time(now),
                "event_log": [
                    *authorization.event_log,
                    {
                        "event": "spent",
                        "amount_usdc": self._format_amount(amount),
                        "payment_id": request.payment_id,
                        "created_at": self._format_time(now),
                    },
                ],
            }
        )
        self._save_record(updated)
        return AuthorizationCheckResult(
            authorization_id=updated.authorization_id,
            approved=True,
            status=updated.status,
            reason="spent",
            amount_usdc=self._format_amount(amount),
            remaining_amount_usdc=updated.remaining_amount_usdc,
        )

    def revoke_authorization(self, authorization_id: str) -> BudgetAuthorization | None:
        authorization = self.get_authorization(authorization_id)
        if authorization is None:
            return None
        now = self._utc_now()
        updated = authorization.model_copy(
            update={
                "status": "revoked",
                "updated_at": self._format_time(now),
                "event_log": [
                    *authorization.event_log,
                    {"event": "revoked", "created_at": self._format_time(now)},
                ],
            }
        )
        self._save_record(updated)
        return updated

    def _load_latest(self) -> dict[str, BudgetAuthorization]:
        if not self.storage_file.exists():
            return {}
        records: dict[str, BudgetAuthorization] = {}
        with self.storage_file.open() as handle:
            for line in handle:
                if not line.strip():
                    continue
                record = BudgetAuthorization(**json.loads(line))
                records[record.authorization_id] = record
        return records

    def _save_record(self, authorization: BudgetAuthorization) -> None:
        self.storage_file.parent.mkdir(parents=True, exist_ok=True)
        with self.storage_file.open("a") as handle:
            handle.write(json.dumps(authorization.to_dict(), ensure_ascii=False) + "\n")

    def _normalize_status(self, authorization: BudgetAuthorization) -> BudgetAuthorization:
        if authorization.status != "active":
            return authorization
        if datetime.fromisoformat(authorization.expires_at.removesuffix("Z")) > self._utc_now():
            return authorization
        now = self._utc_now()
        updated = authorization.model_copy(
            update={
                "status": "expired",
                "updated_at": self._format_time(now),
                "event_log": [
                    *authorization.event_log,
                    {"event": "expired", "created_at": self._format_time(now)},
                ],
            }
        )
        self._save_record(updated)
        return updated

    @staticmethod
    def _parse_amount(value: str) -> Decimal:
        try:
            amount = Decimal(str(value))
        except (InvalidOperation, ValueError) as exc:
            raise ValueError("amount_usdc must be a valid decimal string") from exc
        if amount < 0:
            raise ValueError("amount_usdc must be non-negative")
        return amount

    @staticmethod
    def _format_amount(value: Decimal) -> str:
        rendered = format(value, "f")
        if "." in rendered:
            rendered = rendered.rstrip("0").rstrip(".")
        return rendered or "0"

    @staticmethod
    def _utc_now() -> datetime:
        return datetime.utcnow()

    @staticmethod
    def _format_time(value: datetime) -> str:
        return value.isoformat() + "Z"
