# Verification evidence — ORIN

- Review commit: `ad71aec987e38aea9ef98039aadbc69fc40d672c`
- API base URL: `https://orin-md60.onrender.com`
- Authentication: none (public)

## 1. Health check

```bash
curl --fail --silent --show-error https://orin-md60.onrender.com/health
```

Expected response:

```json
{"status":"ok","commit":"ad71aec987e38aea9ef98039aadbc69fc40d672c","service":"orin","version":"3.0.0"}
```

## 2. Deployment proof

```bash
curl --fail --silent --show-error https://orin-md60.onrender.com/.well-known/xagent-verification.json
```

Expected response:

```json
{"schemaVersion":1,"slug":"hillaryikhais-orin","commit":"ad71aec987e38aea9ef98039aadbc69fc40d672c"}
```

## 3. Capability call — evidence → proof

```bash
curl --fail --silent --show-error \
  --request POST https://orin-md60.onrender.com/capabilities/declare \
  --header "content-type: application/json" \
  --data '{"agent_id":"agent-X","version":"v1","code":"det-v1","model":"m1","prompt":"p1","tools":["read"],"skills":["dup"],"config":{},"env":"prod"}'
```

then

```bash
EV=$(curl -fsS -X POST https://orin-md60.onrender.com/evaluations/create \
  -H "content-type: application/json" -d '{"agent_id":"agent-X","capability":"invoice.duplicate_detection"}' \
  | python3 -c "import json,sys;print(json.load(sys.stdin)['eval_id'])")
curl -fsS -X POST https://orin-md60.onrender.com/evaluations/run \
  -H "content-type: application/json" -d "{\"eval_id\":\"$EV\"}"
```

Expected success: `{"status":"VERIFIED","summary":{...,"passed":50,...}}` with `proof.proof_id` starting `OR-` and a 50/50 public + 10/10 adversarial result.

Safe failure response (unknown capability):

```bash
curl -fsS https://orin-md60.onrender.com/capabilities/ghost/nonexistent.cap/status
```

Expected: `{"status":"UNPROVEN","reason":"NO_SUCH_CAPABILITY",...}` — fail-closed, never `VERIFIED`.

Automation: `verification/orin-smoke.sh https://orin-md60.onrender.com` runs all of the above and asserts the health/verification responses. Live output captured at submission time in `verification/smoke-output.txt`.