# Core Account Entry Design

## Goal

Let a user enter the existing Clink Core Account wallet-binding and spending-cap flow from either the Prediction Markets dashboard or Hermes, without moving wallet ownership, signatures, or authorization state into Prediction Markets.

## Boundaries

- Clink Core Account remains the only service that binds wallets and creates spending grants.
- Prediction Markets may request a short-lived Core Account session and return its public URL.
- Hermes may request and relay that URL, but cannot bind wallets, sign messages, or call Core internal APIs directly.
- Polymarket CLOB binding remains a separate Prediction Markets flow.

## Interface

Prediction Markets exposes one explicit operation:

```text
create_core_account_setup_link(user_id)
  -> user_id
  -> account_url
  -> expires_at
  -> status=pending_user_action
  -> next_action=open_core_account_url
```

The MCP tool and dashboard use the same client function. The client calls:

```text
POST {CLINK_CORE_ACCOUNT_SERVICE_URL}/internal/account-sessions
Authorization: Bearer {CLINK_CORE_INTERNAL_API_TOKEN}
{"user_id": "..."}
```

Readiness remains read-only. When the Core wallet or spending grant is missing, it returns `next_action=create_core_account_setup_link`; it does not create a session as a side effect.

## Dashboard

The Account workspace shows Core Account separately from Polymarket Account. Its Core section reports wallet/spending readiness and provides one primary action, `Open Core Account`, which requests a fresh session and redirects the browser to the returned public URL.

## Errors And Security

- Missing Core URL or internal token returns a clear unavailable response and never falls back to shell or a local URL rewrite.
- Core HTTP errors are sanitized into an actionable service error; bearer tokens are never returned or logged.
- The public URL is accepted only from the trusted Core response.
- A fresh link is created only after an explicit MCP or dashboard action.

## Verification

- Unit smoke proves the Core client sends the bearer token and expected payload.
- MCP smoke proves the new tool returns the public URL and stable next action.
- Readiness smoke proves an unbound Core account points to the setup-link operation before Polymarket binding.
- Dashboard smoke proves the Core Account section and button are present.
