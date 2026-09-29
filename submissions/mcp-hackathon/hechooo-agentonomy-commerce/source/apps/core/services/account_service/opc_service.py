from __future__ import annotations

import base64
import hashlib
import hmac
import json
from datetime import UTC, datetime, timedelta
from secrets import token_urlsafe
from typing import Any, Callable

from eth_account import Account
from eth_account.messages import encode_defunct
from sqlalchemy import CheckConstraint, DateTime, ForeignKey, JSON, String, UniqueConstraint, select
from sqlalchemy.orm import Mapped, Session, mapped_column

from shared.hosted_facilitator_protocol import canonical_json_bytes
from shared.opc_protocol import canonical_opc_origin, verify_opc_proof

from .repository import (
    AccountRepository,
    AccountSessionRow,
    Base,
    PublicAccountSessionRow,
    SpendingGrantRow,
    WalletIdentityRow,
    _utc_timestamp,
)
from .schemas import AccountSession, OpcInstallationAuthorization, canonicalize_evm_address
from .service import AccountService


OPC_ACCESS_TOKEN_PREFIX = "agentonomy_opc_v1_"
OPC_TOKEN_TTL = timedelta(seconds=300)
OPC_PAIRING_TTL = timedelta(minutes=10)
OPC_INSTALLATION_PURPOSE = "agentonomy_opc_installation"


class OpcInstallationRow(Base):
    __tablename__ = "opc_installations"
    __table_args__ = (
        CheckConstraint(
            "status IN ('pending', 'active', 'consent_required', 'revoked')",
            name="ck_opc_installation_status",
        ),
        CheckConstraint("scope = 'payments'", name="ck_opc_installation_scope"),
    )

    installation_id: Mapped[str] = mapped_column(String(96), primary_key=True)
    public_jwk: Mapped[dict] = mapped_column(JSON)
    public_jwk_thumbprint: Mapped[str] = mapped_column(String(64), unique=True)
    label: Mapped[str] = mapped_column(String(80))
    status: Mapped[str] = mapped_column(String(32), index=True)
    scope: Mapped[str] = mapped_column(String(32), default="payments")
    user_id: Mapped[str | None] = mapped_column(String(96), index=True)
    wallet_identity_id: Mapped[str | None] = mapped_column(
        ForeignKey("wallet_identities.wallet_identity_id"), index=True
    )
    spending_grant_id: Mapped[str | None] = mapped_column(
        ForeignKey("spending_grants.spending_grant_id"), index=True
    )
    consent_expires_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), index=True
    )
    consent_hash: Mapped[str | None] = mapped_column(String(64))
    approved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))


class OpcPairingRow(Base):
    __tablename__ = "opc_pairings"
    __table_args__ = (
        UniqueConstraint(
            "installation_id", "request_id", name="uq_opc_pairing_installation_request"
        ),
        CheckConstraint(
            "status IN ('pending', 'claimed', 'linked', 'expired', 'revoked')",
            name="ck_opc_pairing_status",
        ),
    )

    pairing_id: Mapped[str] = mapped_column(String(96), primary_key=True)
    installation_id: Mapped[str] = mapped_column(
        ForeignKey("opc_installations.installation_id"), index=True
    )
    request_id: Mapped[str] = mapped_column(String(128))
    request_fingerprint: Mapped[str] = mapped_column(String(64))
    public_account_session_id: Mapped[str] = mapped_column(
        ForeignKey("public_account_sessions.public_account_session_id"), index=True
    )
    target_user_id: Mapped[str] = mapped_column(String(96), index=True)
    status: Mapped[str] = mapped_column(String(16), index=True)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)
    linked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))


class OpcAccessCredentialRow(Base):
    __tablename__ = "opc_access_credentials"
    __table_args__ = (
        UniqueConstraint(
            "installation_id", "request_id", name="uq_opc_credential_installation_request"
        ),
        CheckConstraint(
            "status IN ('active', 'revoked')", name="ck_opc_credential_status"
        ),
    )

    credential_id: Mapped[str] = mapped_column(String(96), primary_key=True)
    installation_id: Mapped[str] = mapped_column(
        ForeignKey("opc_installations.installation_id"), index=True
    )
    request_id: Mapped[str] = mapped_column(String(128))
    request_fingerprint: Mapped[str] = mapped_column(String(64))
    token_digest: Mapped[str] = mapped_column(String(64), unique=True)
    status: Mapped[str] = mapped_column(String(16), index=True)
    issued_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))


def _as_utc(value: datetime) -> datetime:
    result = _utc_timestamp(value)
    if result is None:
        raise ValueError("timestamp is required")
    return result


def _b64url(value: bytes) -> str:
    return base64.urlsafe_b64encode(value).rstrip(b"=").decode("ascii")


def _jwk_thumbprint(public_jwk: dict[str, str]) -> str:
    return _b64url(hashlib.sha256(canonical_json_bytes(public_jwk)).digest())


def _proof_fingerprint(claims: dict[str, Any]) -> str:
    semantic = {
        "action": claims["action"],
        "installation_id": claims["installation_id"],
        "request_id": claims["request_id"],
    }
    if "label" in claims:
        semantic["label"] = claims["label"]
    return hashlib.sha256(canonical_json_bytes(semantic)).hexdigest()


def _lock_by_id(
    repository: AccountRepository,
    session: Session,
    row_type,
    identifier_column,
    identifier: str,
):
    statement = select(row_type).where(identifier_column == identifier)
    if repository.engine.dialect.name != "sqlite":
        statement = statement.with_for_update()
    return session.scalar(statement)


def _bind_new_grant_installation(
    repository: AccountRepository,
    session: Session,
    *,
    account_session: AccountSessionRow,
    grant: SpendingGrantRow,
    now: datetime,
) -> None:
    """Bind the signed device clause inside the grant creation transaction."""

    terms = (account_session.payload or {}).get("terms") or {}
    clause_value = terms.get("opc_installation")
    if clause_value is None:
        return
    clause = OpcInstallationAuthorization.model_validate(clause_value)
    if account_session.created_by_public_account_session_id is None:
        raise ValueError("OPC installation requires an account session")
    pairing = _lock_by_id(
        repository, session, OpcPairingRow, OpcPairingRow.pairing_id, clause.pairing_id
    )
    if pairing is None or pairing.installation_id != clause.installation_id:
        raise ValueError("OPC pairing was not found")
    public_session = repository._locked_public_account_session(
        session, account_session.created_by_public_account_session_id
    )
    installation = _lock_by_id(
        repository,
        session,
        OpcInstallationRow,
        OpcInstallationRow.installation_id,
        clause.installation_id,
    )
    if installation is None:
        raise ValueError("OPC installation was not found")
    if installation.status == "revoked":
        raise ValueError("OPC installation is revoked")
    if installation.status not in {"pending", "consent_required"}:
        raise ValueError("OPC installation is not awaiting consent")
    if pairing.status not in {"pending", "claimed"} or _as_utc(pairing.expires_at) <= now:
        raise ValueError("OPC pairing is not available")
    if (
        pairing.target_user_id != grant.user_id
        or pairing.public_account_session_id
        != account_session.created_by_public_account_session_id
        or public_session is None
        or public_session.user_id != grant.user_id
        or public_session.status != "active"
        or _as_utc(public_session.expires_at) <= now
    ):
        raise ValueError("OPC pairing account session mismatch")
    if (
        installation.public_jwk != clause.public_jwk
        or installation.public_jwk_thumbprint != clause.public_jwk_thumbprint
        or installation.label != clause.label
        or installation.scope != clause.scope
    ):
        raise ValueError("OPC installation clause mismatch")
    if installation.user_id is not None and (
        installation.user_id != grant.user_id
        or installation.wallet_identity_id != grant.wallet_identity_id
    ):
        raise ValueError("OPC installation account binding mismatch")
    consent_expires_at = _as_utc(clause.consent_expires_at)
    if consent_expires_at <= now or consent_expires_at > _as_utc(grant.expires_at):
        raise ValueError("OPC installation consent expiry is invalid")

    installation.status = "active"
    installation.user_id = grant.user_id
    installation.wallet_identity_id = grant.wallet_identity_id
    installation.spending_grant_id = grant.spending_grant_id
    installation.consent_expires_at = consent_expires_at
    installation.consent_hash = hashlib.sha256(
        canonical_json_bytes(clause.model_dump(mode="json"))
    ).hexdigest()
    installation.approved_at = now
    installation.updated_at = now
    pairing.status = "linked"
    pairing.linked_at = now
    pairing.updated_at = now
    repository._append_account_audit(
        session,
        event_type="opc_installation_linked",
        user_id=grant.user_id,
        agent_id=grant.agent_id,
        created_at=now,
        payload={
            "installation_id": installation.installation_id,
            "wallet_identity_id": grant.wallet_identity_id,
            "spending_grant_id": grant.spending_grant_id,
            "pairing_id": pairing.pairing_id,
        },
    )


def _invalidate_grant_installations(
    repository: AccountRepository,
    session: Session,
    *,
    spending_grant_id: str,
    now: datetime,
) -> None:
    statement = select(OpcInstallationRow).where(
        OpcInstallationRow.spending_grant_id == spending_grant_id,
        OpcInstallationRow.status == "active",
    )
    if repository.engine.dialect.name != "sqlite":
        statement = statement.with_for_update()
    installations = session.scalars(statement).all()
    for installation in installations:
        installation.status = "consent_required"
        installation.updated_at = now
        _revoke_credentials(session, installation.installation_id, now)
        if installation.user_id is not None:
            repository._append_account_audit(
                session,
                event_type="opc_installation_consent_required",
                user_id=installation.user_id,
                agent_id="hermes",
                created_at=now,
                payload={
                    "installation_id": installation.installation_id,
                    "spending_grant_id": spending_grant_id,
                },
            )


def _revoke_credentials(session: Session, installation_id: str, now: datetime) -> None:
    rows = session.scalars(
        select(OpcAccessCredentialRow).where(
            OpcAccessCredentialRow.installation_id == installation_id,
            OpcAccessCredentialRow.status == "active",
        )
    ).all()
    for row in rows:
        row.status = "revoked"
        row.revoked_at = now
        row.updated_at = now


class OpcAccountService:
    def __init__(
        self,
        account: AccountService,
        *,
        origin: str,
        token_signing_key: bytes,
        clock: Callable[[], datetime] | None = None,
        allow_loopback_http: bool = False,
        account_origin: str | None = None,
        mcp_url: str | None = None,
    ) -> None:
        if not isinstance(token_signing_key, bytes) or len(token_signing_key) < 32:
            raise ValueError("OPC token signing key must contain at least 32 bytes")
        self.account = account
        self.repository = account.repository
        self.origin = canonical_opc_origin(
            origin, allow_loopback_http=allow_loopback_http
        )
        self.account_origin = canonical_opc_origin(
            account_origin or origin, allow_loopback_http=allow_loopback_http
        )
        self.mcp_url = mcp_url or f"{self.origin}/mcp"
        if self.mcp_url != f"{self.origin}/mcp":
            raise ValueError("OPC MCP URL must be the public origin /mcp endpoint")
        self.token_signing_key = token_signing_key
        self.clock = clock or (lambda: datetime.now(UTC))
        self.allow_loopback_http = allow_loopback_http
        self.repository.create_schema()

    def create_pairing(self, proof: str) -> dict[str, Any]:
        now = self._now()
        claims = self._proof(proof, action="pair", now=now)
        installation_id = claims["installation_id"]
        request_id = claims["request_id"]
        fingerprint = _proof_fingerprint(claims)
        public_jwk = claims["public_jwk"]
        label = claims.get("label", "OPC installation")
        pairing_id = self._identifier("opc_pair_", installation_id, request_id)
        public_session_id = self._identifier("public_opc_", pairing_id)
        public_token = self._opaque("public-session", pairing_id)
        expires_at = now + OPC_PAIRING_TTL

        with self.repository._write_session() as session:
            installation = _lock_by_id(
                self.repository,
                session,
                OpcInstallationRow,
                OpcInstallationRow.installation_id,
                installation_id,
            )
            if installation is not None:
                if installation.status == "revoked":
                    raise ValueError("OPC installation is revoked")
                if installation.public_jwk != public_jwk:
                    raise ValueError("OPC installation identity conflict")
            existing = _lock_by_id(
                self.repository,
                session,
                OpcPairingRow,
                OpcPairingRow.pairing_id,
                pairing_id,
            )
            if existing is not None:
                if existing.request_fingerprint != fingerprint:
                    raise ValueError("OPC pairing request id conflicts")
                return self._pairing_response(existing, installation)
            target_user_id = (
                installation.user_id
                if installation is not None and installation.user_id is not None
                else self._identifier("opc_user_", installation_id)
            )
            if installation is None:
                installation = OpcInstallationRow(
                    installation_id=installation_id,
                    public_jwk=public_jwk,
                    public_jwk_thumbprint=_jwk_thumbprint(public_jwk),
                    label=label,
                    status="pending",
                    scope="payments",
                    user_id=None,
                    wallet_identity_id=None,
                    spending_grant_id=None,
                    consent_expires_at=None,
                    consent_hash=None,
                    approved_at=None,
                    revoked_at=None,
                    created_at=now,
                    updated_at=now,
                )
                session.add(installation)
            elif installation.label != label:
                raise ValueError("OPC installation label conflicts")
            public_session = session.get(PublicAccountSessionRow, public_session_id)
            if public_session is None:
                session.add(
                    PublicAccountSessionRow(
                        public_account_session_id=public_session_id,
                        token_digest=hashlib.sha256(public_token.encode()).hexdigest(),
                        browser_session_digest=None,
                        csrf_token_digest=None,
                        user_id=target_user_id,
                        purpose="clink_account_console",
                        status="active",
                        expires_at=expires_at,
                        exchanged_at=None,
                        authenticated_wallet_identity_id=None,
                        authenticated_at=None,
                        last_accessed_at=None,
                        revoked_at=None,
                        created_at=now,
                        updated_at=now,
                    )
                )
                session.flush()
            pairing = OpcPairingRow(
                pairing_id=pairing_id,
                installation_id=installation_id,
                request_id=request_id,
                request_fingerprint=fingerprint,
                public_account_session_id=public_session_id,
                target_user_id=target_user_id,
                status="active" if installation.status == "active" else "pending",
                expires_at=expires_at,
                linked_at=now if installation.status == "active" else None,
                created_at=now,
                updated_at=now,
            )
            # The persisted pairing state uses linked, while the public response
            # intentionally exposes the smaller pending/active vocabulary.
            if pairing.status == "active":
                pairing.status = "linked"
            session.add(pairing)
            session.flush()
            return self._pairing_response(pairing, installation)

    def pairing(self, pairing_id: str) -> dict[str, Any]:
        with self.repository.sessions() as session:
            row = session.get(OpcPairingRow, pairing_id)
        if row is None:
            raise ValueError("OPC pairing was not found")
        return self._pairing_record(row)

    def browser_pairing(self, public_account_session_id: str) -> dict[str, Any] | None:
        """Read only the device belonging to this server-resolved browser session."""
        now = self._now()
        with self.repository.sessions() as session:
            rows = session.scalars(select(OpcPairingRow).where(
                OpcPairingRow.public_account_session_id == public_account_session_id
            ).limit(2)).all()
            if not rows:
                return None
            if len(rows) != 1:
                raise ValueError("OPC browser pairing is ambiguous")
            pairing = rows[0]
            installation = session.get(OpcInstallationRow, pairing.installation_id)
            if installation is None:
                raise ValueError("OPC browser installation is unavailable")
            status = pairing.status
            if installation.status == "revoked" or status == "revoked":
                status = "revoked"
            elif status == "linked":
                try:
                    self._validate_active_installation(session, installation, now=now)
                except ValueError:
                    status = "consent_required"
                else:
                    status = "active"
            elif status == "expired" or _as_utc(pairing.expires_at) <= now:
                status = "expired"
            elif installation.status == "consent_required":
                status = "consent_required"
            return {
                "pairing_id": pairing.pairing_id,
                "installation_id": installation.installation_id,
                "label": installation.label,
                "public_jwk_thumbprint": installation.public_jwk_thumbprint,
                "scope": installation.scope,
                "agent_id": "hermes",
                "status": status,
                "expires_at": _as_utc(pairing.expires_at).isoformat(),
                "consent_expires_at": _utc_timestamp(installation.consent_expires_at),
                "wallet_identity_id": installation.wallet_identity_id,
                "spending_grant_id": installation.spending_grant_id,
            }

    def installation(self, installation_id: str) -> dict[str, Any]:
        with self.repository.sessions() as session:
            row = session.get(OpcInstallationRow, installation_id)
        if row is None:
            raise ValueError("OPC installation was not found")
        return self._installation_record(row)

    def authorization_scope(
        self,
        installation_id: str,
        *,
        user_id: str,
        agent_id: str,
    ) -> tuple[str, str]:
        """Resolve one active installation to its exact wallet and grant."""
        now = self._now()
        with self.repository.sessions() as session:
            installation = session.get(OpcInstallationRow, installation_id)
            grant, identity = self._validate_active_installation(
                session, installation, now=now
            )
            if installation.user_id != user_id or grant.agent_id != agent_id:
                raise ValueError("OPC installation authority is unavailable")
            return identity.wallet_identity_id, grant.spending_grant_id

    def claim_pairing(
        self,
        pairing_id: str,
        *,
        user_id: str,
        public_account_session_id: str,
    ) -> dict[str, Any]:
        now = self._now()
        with self.repository._write_session() as session:
            pairing = _lock_by_id(
                self.repository,
                session,
                OpcPairingRow,
                OpcPairingRow.pairing_id,
                pairing_id,
            )
            if pairing is None:
                raise ValueError("OPC pairing was not found")
            installation = _lock_by_id(
                self.repository,
                session,
                OpcInstallationRow,
                OpcInstallationRow.installation_id,
                pairing.installation_id,
            )
            if installation is None or installation.status == "revoked":
                raise ValueError("OPC installation is revoked")
            if _as_utc(pairing.expires_at) <= now or pairing.status not in {
                "pending",
                "claimed",
            }:
                raise ValueError("OPC pairing is not available")
            public_session = self.repository._locked_public_account_session(
                session, public_account_session_id
            )
            if (
                public_session is None
                or public_session.user_id != user_id
                or public_session.status != "active"
                or _as_utc(public_session.expires_at) <= now
            ):
                raise ValueError("public account session is unavailable")
            old_public_session_id = pairing.public_account_session_id
            pairing.target_user_id = user_id
            pairing.public_account_session_id = public_account_session_id
            pairing.status = "claimed"
            pairing.updated_at = now
            if old_public_session_id != public_account_session_id:
                old_session = self.repository._locked_public_account_session(
                    session, old_public_session_id
                )
                if old_session is not None and old_session.status == "active":
                    old_session.status = "revoked"
                    old_session.revoked_at = now
                    old_session.updated_at = now
            return self._pairing_record(pairing)

    def create_installation_challenge(
        self,
        pairing_id: str,
        *,
        user_id: str,
        public_account_session_id: str,
        spending_grant_id: str,
    ) -> dict[str, Any]:
        now = self._now()
        with self.repository._write_session() as session:
            grant_hint = session.get(SpendingGrantRow, spending_grant_id)
            if grant_hint is None:
                raise ValueError("Hermes spending grant is not active")
            identity = self.repository._locked_wallet_identity(
                session, grant_hint.wallet_identity_id
            )
            grant = self.repository._locked_grant(session, spending_grant_id)
            if (
                grant is None
                or grant.wallet_identity_id != grant_hint.wallet_identity_id
                or grant.user_id != user_id
                or grant.agent_id != "hermes"
                or grant.status != "active"
                or _as_utc(grant.starts_at) > now
                or _as_utc(grant.expires_at) <= now
            ):
                raise ValueError("Hermes spending grant is not active")
            if (
                identity is None
                or identity.user_id != user_id
                or identity.status != "active"
            ):
                raise ValueError("wallet identity is not active")
            pairing, installation, public_session = self._available_pairing(
                session,
                pairing_id=pairing_id,
                user_id=user_id,
                public_account_session_id=public_account_session_id,
                spending_grant_id=grant.spending_grant_id,
                wallet_identity_id=identity.wallet_identity_id,
                now=now,
            )
            consent_expires_at = min(_as_utc(grant.expires_at), now + timedelta(days=30))
            payload = {
                "pairing_id": pairing.pairing_id,
                "installation_id": installation.installation_id,
                "public_jwk": installation.public_jwk,
                "public_jwk_thumbprint": installation.public_jwk_thumbprint,
                "label": installation.label,
                "scope": installation.scope,
                "consent_expires_at": consent_expires_at.isoformat(),
                "spending_grant_id": grant.spending_grant_id,
                "grant_authorization_hash": self._grant_authorization_hash(grant),
            }
            account_session = AccountSession(
                account_session_id=f"opc_installation_challenge_{token_urlsafe(24)}",
                user_id=user_id,
                wallet_address=identity.wallet_address,
                wallet_identity_id=identity.wallet_identity_id,
                nonce=token_urlsafe(32),
                domain=self.account.domain,
                purpose=OPC_INSTALLATION_PURPOSE,
                created_by_public_account_session_id=public_session.public_account_session_id,
                payload=payload,
                payload_hash=self.account._payload_hash(payload),
                expires_at=now + self.account.challenge_ttl,
                consumed_at=None,
                created_at=now,
            )
            session.add(AccountSessionRow(**account_session.model_dump()))
            message = self._canonical_installation_message(account_session)
            return {
                "session_id": account_session.account_session_id,
                "message_to_sign": message,
                "expires_at": account_session.expires_at,
                "nonce": account_session.nonce,
            }

    def approve_installation(
        self, session_id: str, signed_message: str, signature: str
    ) -> dict[str, Any]:
        now = self._now()
        with self.repository._write_session() as session:
            challenge = self.repository._locked_account_session(session, session_id)
            if challenge is None or challenge.purpose != OPC_INSTALLATION_PURPOSE:
                raise ValueError("OPC installation challenge was not found")
            if challenge.consumed_at is not None:
                raise ValueError("OPC installation challenge already consumed")
            if _as_utc(challenge.expires_at) <= now:
                raise ValueError("OPC installation challenge expired")
            account_session = self.repository._account_session(challenge)
            expected_message = self._canonical_installation_message(account_session)
            if not isinstance(signed_message, str) or not hmac.compare_digest(
                signed_message.encode(), expected_message.encode()
            ):
                raise ValueError("OPC installation message does not match challenge")
            try:
                recovered = Account.recover_message(
                    encode_defunct(text=expected_message), signature=signature
                )
            except (TypeError, ValueError) as exc:
                raise ValueError("invalid OPC installation signature") from exc
            if canonicalize_evm_address(recovered) != challenge.wallet_address:
                raise ValueError("OPC installation signature does not match wallet")
            payload = challenge.payload or {}
            if challenge.payload_hash != self.account._payload_hash(payload):
                raise ValueError("OPC installation challenge payload mismatch")
            identity = self.repository._locked_wallet_identity(
                session, challenge.wallet_identity_id or ""
            )
            grant = self.repository._locked_grant(
                session, payload.get("spending_grant_id", "")
            )
            if (
                grant is None
                or identity is None
                or grant.user_id != challenge.user_id
                or grant.wallet_identity_id != identity.wallet_identity_id
                or grant.agent_id != "hermes"
                or grant.status != "active"
                or identity.user_id != challenge.user_id
                or identity.status != "active"
                or identity.wallet_address != challenge.wallet_address
                or _as_utc(grant.starts_at) > now
                or _as_utc(grant.expires_at) <= now
            ):
                raise ValueError("OPC installation authority is unavailable")
            if payload.get("grant_authorization_hash") != self._grant_authorization_hash(grant):
                raise ValueError("OPC installation grant authority has changed; request fresh consent")
            pairing, installation, _public_session = self._available_pairing(
                session,
                pairing_id=payload.get("pairing_id", ""),
                user_id=challenge.user_id,
                public_account_session_id=(
                    challenge.created_by_public_account_session_id or ""
                ),
                spending_grant_id=grant.spending_grant_id,
                wallet_identity_id=identity.wallet_identity_id,
                now=now,
            )
            clause = OpcInstallationAuthorization(
                pairing_id=pairing.pairing_id,
                installation_id=installation.installation_id,
                public_jwk=installation.public_jwk,
                public_jwk_thumbprint=installation.public_jwk_thumbprint,
                label=installation.label,
                scope=installation.scope,
                consent_expires_at=datetime.fromisoformat(payload["consent_expires_at"]),
            )
            consent_expires_at = _as_utc(clause.consent_expires_at)
            if consent_expires_at <= now or consent_expires_at > _as_utc(grant.expires_at):
                raise ValueError("OPC installation consent expiry is invalid")
            installation.status = "active"
            installation.user_id = challenge.user_id
            installation.wallet_identity_id = identity.wallet_identity_id
            installation.spending_grant_id = grant.spending_grant_id
            installation.consent_expires_at = consent_expires_at
            installation.consent_hash = hashlib.sha256(
                canonical_json_bytes(clause.model_dump(mode="json"))
            ).hexdigest()
            installation.approved_at = now
            installation.updated_at = now
            pairing.status = "linked"
            pairing.linked_at = now
            pairing.updated_at = now
            challenge.consumed_at = now
            self.repository._append_account_audit(
                session,
                event_type="opc_installation_linked",
                user_id=challenge.user_id,
                agent_id="hermes",
                created_at=now,
                payload={
                    "installation_id": installation.installation_id,
                    "wallet_identity_id": identity.wallet_identity_id,
                    "spending_grant_id": grant.spending_grant_id,
                    "pairing_id": pairing.pairing_id,
                },
            )
            return self._installation_record(installation)

    def grant_installation_clause(
        self,
        pairing_id: str,
        *,
        user_id: str,
        public_account_session_id: str,
        grant_expires_at: datetime,
    ) -> OpcInstallationAuthorization:
        now = self._now()
        with self.repository.sessions() as session:
            pairing = session.get(OpcPairingRow, pairing_id)
            installation = (
                session.get(OpcInstallationRow, pairing.installation_id)
                if pairing is not None
                else None
            )
            public_session = session.get(PublicAccountSessionRow, public_account_session_id)
        if (
            pairing is None
            or installation is None
            or installation.status not in {"pending", "consent_required"}
            or pairing.status not in {"pending", "claimed"}
            or pairing.target_user_id != user_id
            or pairing.public_account_session_id != public_account_session_id
            or _as_utc(pairing.expires_at) <= now
            or public_session is None
            or public_session.user_id != user_id
            or public_session.status != "active"
            or _as_utc(public_session.expires_at) <= now
        ):
            raise ValueError("OPC pairing is not available")
        consent_expires_at = min(
            _as_utc(grant_expires_at), now + timedelta(days=30)
        )
        if consent_expires_at <= now:
            raise ValueError("OPC installation consent expiry is invalid")
        return OpcInstallationAuthorization(
            pairing_id=pairing.pairing_id,
            installation_id=installation.installation_id,
            public_jwk=installation.public_jwk,
            public_jwk_thumbprint=installation.public_jwk_thumbprint,
            label=installation.label,
            scope=installation.scope,
            consent_expires_at=consent_expires_at,
        )

    def issue_token(self, proof: str) -> dict[str, Any]:
        now = self._now()
        claims = self._proof(proof, action="token", now=now)
        installation_id = claims["installation_id"]
        fingerprint = _proof_fingerprint(claims)
        request_id = claims["request_id"]
        credential_id = self._identifier("opc_credential_", installation_id, request_id)
        with self.repository._write_session() as session:
            installation = _lock_by_id(
                self.repository,
                session,
                OpcInstallationRow,
                OpcInstallationRow.installation_id,
                installation_id,
            )
            grant, _identity = self._validate_active_installation(
                session, installation, now=now
            )
            existing = _lock_by_id(
                self.repository,
                session,
                OpcAccessCredentialRow,
                OpcAccessCredentialRow.credential_id,
                credential_id,
            )
            if existing is not None:
                if existing.request_fingerprint != fingerprint:
                    raise ValueError("OPC token request id conflicts")
                return self._token_response(existing)
            expires_at = min(
                now + OPC_TOKEN_TTL,
                _as_utc(installation.consent_expires_at),
                _as_utc(grant.expires_at),
            )
            if expires_at <= now + timedelta(seconds=60):
                raise ValueError("OPC installation authority expires too soon")
            _revoke_credentials(session, installation_id, now)
            credential = OpcAccessCredentialRow(
                credential_id=credential_id,
                installation_id=installation_id,
                request_id=request_id,
                request_fingerprint=fingerprint,
                token_digest="",
                status="active",
                issued_at=now,
                expires_at=expires_at,
                revoked_at=None,
                created_at=now,
                updated_at=now,
            )
            token = self._access_token(credential)
            credential.token_digest = hashlib.sha256(token.encode()).hexdigest()
            session.add(credential)
            self.repository._append_account_audit(
                session,
                event_type="opc_credential_issued",
                user_id=installation.user_id,
                agent_id="hermes",
                created_at=now,
                payload={
                    "installation_id": installation_id,
                    "credential_id": credential_id,
                    "spending_grant_id": installation.spending_grant_id,
                    "expires_at": expires_at.isoformat(),
                },
            )
            return self._token_response(credential)

    def authenticate_access_token(self, access_token: str) -> dict[str, Any]:
        if (
            not isinstance(access_token, str)
            or not access_token.startswith(OPC_ACCESS_TOKEN_PREFIX)
            or len(access_token) > 512
        ):
            raise ValueError("OPC access token is invalid")
        now = self._now()
        token_digest = hashlib.sha256(access_token.encode()).hexdigest()
        with self.repository.sessions() as session:
            credential = session.scalar(
                select(OpcAccessCredentialRow).where(
                    OpcAccessCredentialRow.token_digest == token_digest
                )
            )
            installation = (
                session.get(OpcInstallationRow, credential.installation_id)
                if credential is not None
                else None
            )
            if credential is None or installation is None:
                raise ValueError("OPC access token is invalid")
            grant, identity = self._validate_active_installation(
                session, installation, now=now
            )
            if credential.status != "active":
                raise ValueError("OPC access token is revoked")
            if _as_utc(credential.expires_at) <= now:
                raise ValueError("OPC access token has expired")
            expected = self._access_token(credential)
            if not hmac.compare_digest(access_token.encode(), expected.encode()):
                raise ValueError("OPC access token is invalid")
            return {
                "issuer": "opc",
                "installation_id": installation.installation_id,
                "user_id": installation.user_id,
                "wallet_identity_id": identity.wallet_identity_id,
                "agent_id": "hermes",
                "spending_grant_id": grant.spending_grant_id,
                "scope": installation.scope,
                "credential_id": credential.credential_id,
                "expires_at": int(_as_utc(credential.expires_at).timestamp()),
            }

    def status(self, proof: str) -> dict[str, Any]:
        now = self._now()
        claims = self._proof(proof, action="status", now=now)
        with self.repository.sessions() as session:
            row = session.get(OpcInstallationRow, claims["installation_id"])
        if row is None:
            return {"installation_id": claims["installation_id"], "status": "unpaired"}
        return self._installation_record(row)

    def revoke(self, proof: str) -> dict[str, Any]:
        now = self._now()
        claims = self._proof(proof, action="revoke", now=now)
        installation_id = claims["installation_id"]
        with self.repository._write_session() as session:
            installation = _lock_by_id(
                self.repository,
                session,
                OpcInstallationRow,
                OpcInstallationRow.installation_id,
                installation_id,
            )
            if installation is None:
                installation = OpcInstallationRow(
                    installation_id=installation_id,
                    public_jwk=claims["public_jwk"],
                    public_jwk_thumbprint=_jwk_thumbprint(claims["public_jwk"]),
                    label="Revoked OPC installation",
                    status="revoked",
                    scope="payments",
                    user_id=None,
                    wallet_identity_id=None,
                    spending_grant_id=None,
                    consent_expires_at=None,
                    consent_hash=None,
                    approved_at=None,
                    revoked_at=now,
                    created_at=now,
                    updated_at=now,
                )
                session.add(installation)
            elif installation.public_jwk != claims["public_jwk"]:
                raise ValueError("OPC installation identity conflict")
            else:
                installation.status = "revoked"
                installation.revoked_at = installation.revoked_at or now
                installation.updated_at = now
                _revoke_credentials(session, installation_id, now)
                pairings = session.scalars(
                    select(OpcPairingRow).where(
                        OpcPairingRow.installation_id == installation_id,
                        OpcPairingRow.status != "revoked",
                    )
                ).all()
                for pairing in pairings:
                    pairing.status = "revoked"
                    pairing.updated_at = now
            if installation.user_id is not None:
                self.repository._append_account_audit(
                    session,
                    event_type="opc_installation_revoked",
                    user_id=installation.user_id,
                    agent_id="hermes",
                    created_at=now,
                    payload={"installation_id": installation_id},
                )
        return {"installation_id": installation_id, "status": "revoked"}

    def _available_pairing(
        self,
        session: Session,
        *,
        pairing_id: str,
        user_id: str,
        public_account_session_id: str,
        spending_grant_id: str,
        wallet_identity_id: str,
        now: datetime,
    ):
        pairing = _lock_by_id(
            self.repository,
            session,
            OpcPairingRow,
            OpcPairingRow.pairing_id,
            pairing_id,
        )
        installation = (
            _lock_by_id(
                self.repository,
                session,
                OpcInstallationRow,
                OpcInstallationRow.installation_id,
                pairing.installation_id,
            )
            if pairing is not None
            else None
        )
        public_session = self.repository._locked_public_account_session(
            session, public_account_session_id
        )
        # A signed amendment invalidates device consent. The same still-live
        # browser can renew only that exact binding, never reclaim another grant.
        refreshing_linked = (
            pairing is not None
            and installation is not None
            and pairing.status == "linked"
            and installation.status == "consent_required"
            and installation.user_id == user_id
            and installation.wallet_identity_id == wallet_identity_id
            and installation.spending_grant_id == spending_grant_id
        )
        if (
            pairing is None
            or installation is None
            or installation.status not in {"pending", "consent_required"}
            or (pairing.status not in {"pending", "claimed"} and not refreshing_linked)
            or pairing.target_user_id != user_id
            or pairing.public_account_session_id != public_account_session_id
            or _as_utc(pairing.expires_at) <= now
            or public_session is None
            or public_session.user_id != user_id
            or public_session.status != "active"
            or _as_utc(public_session.expires_at) <= now
        ):
            raise ValueError("OPC pairing is not available")
        return pairing, installation, public_session

    def _validate_active_installation(
        self,
        session: Session,
        installation: OpcInstallationRow | None,
        *,
        now: datetime,
    ) -> tuple[SpendingGrantRow, WalletIdentityRow]:
        if installation is None:
            raise ValueError("OPC installation was not found")
        if installation.status == "revoked":
            raise ValueError("OPC installation is revoked")
        if installation.status != "active":
            raise ValueError("OPC installation is not active")
        if (
            installation.consent_expires_at is None
            or _as_utc(installation.consent_expires_at) <= now
        ):
            raise ValueError("OPC installation consent has expired")
        identity = session.get(WalletIdentityRow, installation.wallet_identity_id)
        grant = session.get(SpendingGrantRow, installation.spending_grant_id)
        if (
            identity is None
            or grant is None
            or identity.status != "active"
            or identity.user_id != installation.user_id
            or grant.status != "active"
            or grant.agent_id != "hermes"
            or grant.user_id != installation.user_id
            or grant.wallet_identity_id != identity.wallet_identity_id
            or _as_utc(grant.starts_at) > now
            or _as_utc(grant.expires_at) <= now
            or _as_utc(installation.consent_expires_at) > _as_utc(grant.expires_at)
        ):
            raise ValueError("OPC installation authority is unavailable")
        return grant, identity

    def _proof(self, proof: str, *, action: str, now: datetime) -> dict[str, Any]:
        return verify_opc_proof(
            proof,
            origin=self.origin,
            action=action,
            now=int(now.timestamp()),
            allow_loopback_http=self.allow_loopback_http,
        )

    def _now(self) -> datetime:
        value = self.clock()
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("clock must return a timezone-aware datetime")
        return value.astimezone(UTC)

    def _identifier(self, prefix: str, *parts: str) -> str:
        digest = hmac.new(
            self.token_signing_key,
            (prefix + "\x00" + "\x00".join(parts)).encode(),
            hashlib.sha256,
        ).hexdigest()
        return prefix + digest[:40]

    def _opaque(self, purpose: str, *parts: str) -> str:
        digest = hmac.new(
            self.token_signing_key,
            (purpose + "\x00" + "\x00".join(parts)).encode(),
            hashlib.sha256,
        ).digest()
        return _b64url(digest)

    def _access_token(self, credential: OpcAccessCredentialRow) -> str:
        payload = {
            "credential_id": credential.credential_id,
            "installation_id": credential.installation_id,
            "issued_at": int(_as_utc(credential.issued_at).timestamp()),
            "expires_at": int(_as_utc(credential.expires_at).timestamp()),
        }
        return OPC_ACCESS_TOKEN_PREFIX + self._opaque(
            "access-token", canonical_json_bytes(payload).decode("utf-8")
        )

    def _token_response(self, credential: OpcAccessCredentialRow) -> dict[str, Any]:
        return {
            "installation_id": credential.installation_id,
            "access_token": self._access_token(credential),
            "token_type": "Bearer",
            "expires_at": int(_as_utc(credential.expires_at).timestamp()),
            "mcp_url": self.mcp_url,
        }

    def _pairing_response(
        self, pairing: OpcPairingRow, installation: OpcInstallationRow | None
    ) -> dict[str, Any]:
        public_token = self._opaque("public-session", pairing.pairing_id)
        status = "active" if installation is not None and installation.status == "active" else "pending"
        return {
            "installation_id": pairing.installation_id,
            "pairing_id": pairing.pairing_id,
            "verification_uri": f"{self.account_origin}/account/{public_token}",
            "expires_at": int(_as_utc(pairing.expires_at).timestamp()),
            "status": status,
        }

    @staticmethod
    def _pairing_record(row: OpcPairingRow) -> dict[str, Any]:
        return {
            "pairing_id": row.pairing_id,
            "installation_id": row.installation_id,
            "public_account_session_id": row.public_account_session_id,
            "target_user_id": row.target_user_id,
            "status": row.status,
            "expires_at": _as_utc(row.expires_at),
        }

    @staticmethod
    def _installation_record(row: OpcInstallationRow) -> dict[str, Any]:
        return {
            "installation_id": row.installation_id,
            "status": row.status,
            "label": row.label,
            "scope": row.scope,
            "user_id": row.user_id,
            "wallet_identity_id": row.wallet_identity_id,
            "spending_grant_id": row.spending_grant_id,
            "consent_expires_at": _utc_timestamp(row.consent_expires_at),
            "created_at": _as_utc(row.created_at),
            "updated_at": _as_utc(row.updated_at),
        }

    def _grant_authorization_hash(self, grant: SpendingGrantRow) -> str:
        # Bind consent to authority, not mutable accounting counters. In-flight
        # spending must not invalidate an otherwise unchanged device consent.
        terms = self.repository._spending_grant(grant).model_dump(mode="json", include={
            "spending_grant_id", "wallet_identity_id", "user_id", "agent_id",
            "max_amount_usdc", "per_transaction_limit_usdc", "hourly_limit_usdc",
            "daily_limit_usdc", "product_scopes", "venue_scopes", "merchant_scopes",
            "merchant_trust_scopes", "notification_mode", "network_scopes",
            "asset_scopes", "starts_at", "expires_at",
        })
        return hashlib.sha256(canonical_json_bytes(terms)).hexdigest()

    def _canonical_installation_message(self, account_session: AccountSession) -> str:
        payload = account_session.payload or {}
        return "\n".join(
            (
                "Agentonomy OPC Installation",
                f"Domain: {account_session.domain}",
                f"User ID: {account_session.user_id}",
                f"Wallet Identity ID: {account_session.wallet_identity_id}",
                f"Wallet Address: {account_session.wallet_address}",
                f"Hermes Spending Grant ID: {payload.get('spending_grant_id')}",
                f"Grant Authorization Hash: {payload.get('grant_authorization_hash')}",
                f"OPC Pairing ID: {payload.get('pairing_id')}",
                f"OPC Installation ID: {payload.get('installation_id')}",
                "OPC Public Key: "
                f"{json.dumps(payload.get('public_jwk'), sort_keys=True, separators=(',', ':'))}",
                f"OPC Public Key Thumbprint: {payload.get('public_jwk_thumbprint')}",
                f"OPC Label: {payload.get('label')}",
                f"OPC Scope: {payload.get('scope')}",
                f"OPC Consent Expires At: {payload.get('consent_expires_at')}",
                f"Session ID: {account_session.account_session_id}",
                f"Nonce: {account_session.nonce}",
                f"Issued At: {self.account._timestamp(account_session.created_at)}",
                f"Expiration Time: {self.account._timestamp(account_session.expires_at)}",
                f"Purpose: {OPC_INSTALLATION_PURPOSE}",
            )
        )


__all__ = [
    "OPC_ACCESS_TOKEN_PREFIX",
    "OpcAccessCredentialRow",
    "OpcAccountService",
    "OpcInstallationRow",
    "OpcPairingRow",
    "_bind_new_grant_installation",
    "_invalidate_grant_installations",
]
