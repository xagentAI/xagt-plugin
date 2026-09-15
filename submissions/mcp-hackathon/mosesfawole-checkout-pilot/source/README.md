# Checkout Pilot

Checkout Pilot is a demo-first payment-request dashboard built around Moove's current Receive API. It creates one-off hosted checkout links, keeps a merchant reference on every request, and reads settlement status without exposing an API key to the browser.

## Run the demo

Requirements: Node.js 20 or newer.

```powershell
npm start
```

Open `http://127.0.0.1:8787`. Demo mode stores links in memory, moves no money, and clears all records when the process stops.

## Connect Moove later

1. Claim a Moove Handle and configure a default settlement wallet.
2. Create a Receive-scoped key at <https://www.moove.xyz/dashboard/api-keys>.
3. Set both values in the server environment. Use the exact base URL displayed beside the key.

```powershell
$env:MOOVE_API_BASE_URL = "https://api.moove.xyz"
$env:MOOVE_API_KEY = "your-key-from-the-dashboard"
npm start
```

Do not paste the key into this repository or send it in a chat message. Live mode calls only:

- `POST /v1/payment-link`
- `GET /v1/payment-link`
- `GET /v1/payment-link/{id}`

The app does not send, swap, bridge, stake, withdraw, or connect a payer wallet.

## X-Agent deployment contract

The public deployment exposes:

- `GET /health`: returns `status: "ok"` and the deployed source commit.
- `GET /.well-known/xagent-verification.json`: binds the deployment to the submission slug and source commit.
- `GET /api/capabilities`: documents operations, inputs, side effects, and constraints for agent productization.
- `GET /openapi.json`: machine-readable OpenAPI 3.1 contract.

Set `SOURCE_COMMIT` to the exact 40-character commit pushed to the public source repository and set `XAGENT_SUBMISSION_SLUG` to the final `<builder>-checkout-pilot` directory name. The verification endpoint refuses to claim a development or placeholder commit.

## Container deployment

```powershell
docker build -t checkout-pilot .
docker run --rm -p 8787:8787 `
  -e SOURCE_COMMIT=<40-character-public-commit> `
  -e XAGENT_SUBMISSION_SLUG=mosesfawole-checkout-pilot `
  checkout-pilot
```

For the hackathon's public capability review, demo mode is enough to exercise the API without credentials or financial activity. Moove live mode is a separate configuration and should be enabled only when a real pilot is ready.

### Render

The included `render.yaml` is a Blueprint deployment. Create a Render service from the public GitHub repository, set `SOURCE_COMMIT` to the deployed Git commit, and leave the Moove variables blank for demo mode. Render will expose `/health` and the X-Agent verification endpoint over HTTPS.

## Verify

```powershell
npm test
```

## Product wedge

The next defensible step is a merchant pilot: embed the link creator in Telegram or Discord, recruit one real seller, and measure genuine orders, settlement completion, and time saved. Those records become evidence for the Moove Developer Program and material for a Decentralize AI technical article.

## Current constraints

- Moove Receive is live; the public Send, Swap, Bridge, Stake, and Ramp APIs are not.
- Moove currently has no webhooks, so status checks use polite polling.
- Demo records are in-memory only.
- USD labels in this prototype are display labels; settlement behavior is controlled by the merchant's Moove account.
