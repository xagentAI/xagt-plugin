# Verification evidence

Review commit: `1c4740857de59595f8d2bb4501f6e44d00a160f4`

## 1. Health check

```bash
curl --fail --silent --show-error https://checkout-pilot.onrender.com/health
```

Expected response includes:

```json
{"status":"ok","commit":"1c4740857de59595f8d2bb4501f6e44d00a160f4"}
```

## 2. Deployment proof

```bash
curl --fail --silent --show-error https://checkout-pilot.onrender.com/.well-known/xagent-verification.json
```

Expected response:

```json
{"schemaVersion":1,"slug":"mosesfawole-checkout-pilot","commit":"1c4740857de59595f8d2bb4501f6e44d00a160f4"}
```

## 3. Safe capability call

```bash
curl --fail --silent --show-error \
  --request POST https://checkout-pilot.onrender.com/v1/payment-link \
  --header "content-type: application/json" \
  --data '{"amount":"25.00","currency":"USDC","description":"Pilot invoice"}'
```

In demo mode this returns a generated link identifier and payable URL. Invalid amounts are rejected with a 4xx response. No credentials or private keys are required.
