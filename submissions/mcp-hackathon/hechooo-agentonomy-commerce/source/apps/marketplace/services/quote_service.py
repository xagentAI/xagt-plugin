from __future__ import annotations
from shared.commerce import Quote, payment_capability, purchase_execution_mode

class QuoteService:
    def __init__(self, repository, *, native_provider_ids=()):
        self.repository=repository
        self.native_provider_ids=frozenset(native_provider_ids)
    def compare(self, query, network=None, max_price_usd=None, limit=10):
        quotes=[]
        for item in self.repository.search(query,network,max_price_usd,limit):
            trust_tier=item.metadata.get("trust_tier","clink_verified")
            mode=purchase_execution_mode(
                trust_tier=trust_tier,
                provider_id=item.provider_id,
                native_provider_ids=self.native_provider_ids,
            )
            for payment in item.payment_options:
                quotes.append(Quote(offering_id=item.offering_id,provider_id=item.provider_id,name=item.name,endpoint=item.endpoint,payment=payment.model_dump(mode="json"),reputation=self.repository.reputation(item.offering_id),sla=item.metadata.get("sla",{}),trust_tier=trust_tier,verification_source=item.metadata["verification_source"],execution_mode=mode,payment_capability=payment_capability(mode)))
        return sorted(quotes,key=lambda q:(-(q.reputation.get("score") or 0),q.payment.get("price_usd") or 10**9))
