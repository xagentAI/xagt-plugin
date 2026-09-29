from __future__ import annotations
import httpx
from concurrent.futures import ThreadPoolExecutor, wait
from urllib.parse import urlencode


class CoreGatewayError(RuntimeError):
    def __init__(self, message, *, status_code=None, code=None):
        super().__init__(message)
        self.status_code = status_code
        self.code = code

class HttpCoreGateway:
    def __init__(self, *, action_url, policy_url, audit_url, funding_url, account_url="http://127.0.0.1:8019", token, client=None,health_timeout_seconds=0.75,health_deadline_seconds=2.5):
        if not token: raise ValueError("CLINK_CORE_INTERNAL_API_TOKEN is required")
        self.action_url, self.policy_url, self.audit_url, self.funding_url, self.account_url = action_url, policy_url, audit_url, funding_url, account_url
        self.headers = {"Authorization": f"Bearer {token}"}; self.client = client or httpx.Client(timeout=15)
        self.health_timeout_seconds=health_timeout_seconds;self.health_deadline_seconds=health_deadline_seconds
    def _post(self, url, payload):
        response = self.client.post(url, json=payload, headers=self.headers)
        if response.is_error:
            code = None
            message = response.text
            try:
                detail = response.json().get("detail")
                if isinstance(detail, dict):
                    code = detail.get("code")
                    message = detail.get("message") or message
                elif detail:
                    message = str(detail)
            except (TypeError, ValueError):
                pass
            raise CoreGatewayError(
                message,
                status_code=response.status_code,
                code=code,
            )
        return response.json()
    def _get(self, url):
        response = self.client.get(url, headers=self.headers); response.raise_for_status(); return response.json()
    def create_action(self, payload): return self._post(f"{self.action_url}/actions", payload)
    def update_action(self, action_id, payload): return self._post(f"{self.action_url}/actions/{action_id}/update", payload)
    def evaluate_policy(self, payload): return self._post(f"{self.policy_url}/policies/evaluate", payload)
    def audit(self, payload): return self._post(f"{self.audit_url}/audit/events", payload)
    def reserve(self, payload): return self._post(f"{self.funding_url}/funding/spending-reservations", payload)
    def settle(self, reservation_id, payload): return self._post(f"{self.funding_url}/funding/spending-reservations/{reservation_id}/settle", payload)
    def reconcile(self, reservation_id): return self._post(f"{self.funding_url}/funding/spending-reservations/{reservation_id}/reconcile", {})
    def finalize(self, reservation_id, payload): return self._post(f"{self.funding_url}/funding/spending-reservations/{reservation_id}/finalize", payload)
    def release(self, reservation_id, reason): return self._post(f"{self.funding_url}/funding/spending-reservations/{reservation_id}/release", {"reason": reason})
    def reservation(self, reservation_id): return self._get(f"{self.funding_url}/funding/spending-reservations/{reservation_id}")
    def external_finalize(self,reservation_id,payload): return self._post(f"{self.funding_url}/funding/spending-reservations/{reservation_id}/external-finalize",payload)
    def proxy_prepare(self,reservation_id,payload): return self._post(f"{self.funding_url}/funding/spending-reservations/{reservation_id}/proxy-prepare",payload)
    def proxy_finalize(self,reservation_id,payload): return self._post(f"{self.funding_url}/funding/spending-reservations/{reservation_id}/proxy-finalize",payload)
    def funding_readiness(self): return self._get(f"{self.funding_url}/funding/readiness")
    def resolve_authorization(self,payload): return self._post(f"{self.account_url}/internal/authorization-resolution",payload)
    def create_account_session(self,user_id): return self._post(f"{self.account_url}/internal/account-sessions",{"user_id":user_id})
    def wallet_identities(self,user_id):
        query = urlencode({"user_id": user_id})
        return self._get(f"{self.account_url}/internal/wallet-identities?{query}")
    def health(self):
        targets=(
            ("action", self.action_url),
            ("policy", self.policy_url),
            ("audit", self.audit_url),
            ("funding", self.funding_url),
            ("account", self.account_url),
        )
        def probe(name,url):
            try:
                response=self.client.get(f"{url}/healthz",headers=self.headers,timeout=self.health_timeout_seconds)
                response.raise_for_status();payload=response.json()
                return name,"ok" if payload.get("status") in {"ok","ready"} else "degraded"
            except Exception:
                return name,"unavailable"
        executor=ThreadPoolExecutor(max_workers=len(targets),thread_name_prefix="core-health")
        futures={executor.submit(probe,*target):target[0] for target in targets}
        done,pending=wait(futures,timeout=self.health_deadline_seconds)
        services={name:"unavailable" for name,_ in targets}
        for future in done:
            name,state=future.result();services[name]=state
        for future in pending:future.cancel()
        executor.shutdown(wait=False,cancel_futures=True)
        return {
            "status": "ok" if all(value == "ok" for value in services.values()) else "degraded",
            "services": services,
        }
