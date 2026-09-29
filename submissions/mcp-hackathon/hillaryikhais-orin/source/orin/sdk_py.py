"""Orin Python SDK."""
import urllib.request, json

class Orin:
    def __init__(self, base_url):
        self.base = base_url.rstrip("/")

    def _post(self, path, body):
        req = urllib.request.Request(self.base + path, data=json.dumps(body).encode(),
                                     headers={"Content-Type": "application/json"}, method="POST")
        return json.load(urllib.request.urlopen(req))

    def _get(self, path):
        return json.load(urllib.request.urlopen(self.base + path))

    def declare(self, agent):
        return self._post("/capabilities/declare", agent)

    def evaluate(self, agent_id, capability="invoice.duplicate_detection"):
        ev = self._post("/evaluations/create", {"agent_id": agent_id, "capability": capability})
        return self._post("/evaluations/run", {"eval_id": ev["eval_id"]})

    def status(self, agent_id, capability="invoice.duplicate_detection"):
        return self._get(f"/capabilities/{agent_id}/{capability}/status")

    def contract(self, agent_id, capability="invoice.duplicate_detection", scope=None,
                 conditions=None, materiality=None):
        return self._post("/capabilities/contract", {"agent_id": agent_id, "capability": capability,
                          "scope": scope, "conditions": conditions, "materiality": materiality})

    def admit(self, contract_id):
        req = urllib.request.Request(self.base + f"/capabilities/{contract_id}/admit",
                                     data=b"{}", headers={"Content-Type": "application/json"}, method="POST")
        return json.load(urllib.request.urlopen(req))

    def check(self, contract_id, conditions=None, requested=None):
        return self._post(f"/capabilities/{contract_id}/check",
                          {"conditions": conditions, "requested": requested})

    def observe(self, contract_id, changes):
        return self._post(f"/capabilities/{contract_id}/observe", {"changes": changes})
