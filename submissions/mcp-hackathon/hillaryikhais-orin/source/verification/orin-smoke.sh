# Public API base URL (set after deploy)
BASE=""
if [ -n "$BASE" ] && [ -z "$1" ]; then set -- "$BASE"; fi
Q="${1:?usage: orin-smoke.sh <public-base-url>}"
echo "== ORIN public verification vs $Q =="
curl -fsS "$Q/health"
echo
curl -fsS "$Q/.well-known/xagent-verification.json"
echo
/opt/homebrew/bin/python3.14 - "$Q" <<'EOF'
import json, sys, urllib.request
BASE = sys.argv[1]
def post(p, b):
    r = urllib.request.Request(BASE + p, data=json.dumps(b).encode(),
                               headers={"Content-Type": "application/json"}, method="POST")
    return json.load(urllib.request.urlopen(r))
def get(p):
    return json.load(urllib.request.urlopen(BASE + p))
AG = {"agent_id": "agent-X", "version": "v1", "code": "det-v1", "model": "m1",
      "prompt": "p1", "tools": ["read"], "skills": ["dup"], "config": {}, "env": "prod"}
post("/capabilities/declare", AG)
ev = post("/evaluations/create", {"agent_id": "agent-X", "capability": "invoice.duplicate_detection"})
r = post("/evaluations/run", {"eval_id": ev["eval_id"]})
assert r["status"] == "VERIFIED", r
print("VERIFIED:", r["summary"], r["proof"]["proof_id"])
print("status:", get("/capabilities/agent-X/invoice.duplicate_detection/status"))
print("PUBLIC SMOKE OK")
EOF