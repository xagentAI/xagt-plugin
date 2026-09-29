from __future__ import annotations

from shared.models import ClinkServiceManifest, ManifestOffering, PaymentOption, Provider, ServiceOffering


class CandidateNotFoundError(ValueError):
    pass


class ProviderOwnershipConflictError(ValueError):
    pass


class CandidateService:
    def __init__(self, repository):
        self.repository = repository

    def list_candidates(self, domain=None, pay_to=None, query=None, limit=20):
        rows=self.repository.list_bazaar_candidates(
            domain=domain,
            pay_to=pay_to,
            query=query,
            limit=limit,
        )
        return [{"provider":self._provider(row["provider"]),"offering":self._offering(row["offering"])} for row in rows]

    def create_manifest_draft(self, offering_id, wallet_address) -> ClinkServiceManifest:
        status, candidate = self.repository.get_bazaar_candidate_for_claim(
            offering_id,
            wallet_address,
        )
        if status == "not_found":
            raise CandidateNotFoundError("candidate not found")
        if status == "conflict":
            raise ProviderOwnershipConflictError("provider ownership conflict")

        provider = self._provider(candidate["provider"]).model_copy(
            update={
                "source": "clink_manifest",
                "status": "discovered",
                "verified_wallets": [],
            }
        )
        offering = self._offering(candidate["offering"])
        metadata = {
            "claim_source": "cdp_bazaar",
            "claimed_offering_id": offering.offering_id,
        }
        draft = ManifestOffering(
            name=offering.name,
            description=offering.description,
            endpoint=offering.endpoint,
            method=offering.method,
            input_schema=offering.input_schema,
            output_schema=offering.output_schema,
            tags=offering.tags,
            payment_options=offering.payment_options,
            metadata=metadata,
        )
        return ClinkServiceManifest(provider=provider, offerings=[draft])

    @staticmethod
    def _payment(option) -> PaymentOption:
        return PaymentOption(
            scheme=option.scheme,
            network=option.network,
            asset=option.asset,
            amount_atomic=option.amount_atomic,
            pay_to=option.pay_to,
            max_timeout_seconds=option.max_timeout_seconds,
            price_usd=option.price_usd,
            metadata={},
        )

    @staticmethod
    def _provider(provider) -> Provider:
        return Provider(
            provider_id=provider.provider_id,
            name=provider.name,
            domain=provider.domain,
            source=provider.source,
            status=provider.status,
            verified_wallets=[],
            metadata={},
        )

    @classmethod
    def _offering(cls, offering) -> ServiceOffering:
        return ServiceOffering(
            offering_id=offering.offering_id,
            provider_id=offering.provider_id,
            source=offering.source,
            source_id=offering.source_id,
            name=offering.name,
            description=offering.description,
            endpoint=offering.endpoint,
            method=offering.method,
            input_schema=offering.input_schema,
            output_schema=offering.output_schema,
            tags=offering.tags,
            payment_options=[cls._payment(option) for option in offering.payment_options],
            status=offering.status,
            last_synced_at=offering.last_synced_at,
            metadata={},
        )
