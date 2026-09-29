# Verification evidence

## Prerequisites

- Review commit: `<40-character commit SHA>` (pinned at deploy; reported by both endpoints below)
- API base URL: `https://signal-strip-mcp.onrender.com`
- Authentication: none

## 1. Health check

```bash
curl --fail --silent --show-error https://signal-strip-mcp.onrender.com/health
```

Expected response:

```json
{"status":"ok","commit":"<40-character review commit>"}
```

## 2. Deployment proof

```bash
curl --fail --silent --show-error https://signal-strip-mcp.onrender.com/.well-known/xagent-verification.json
```

Expected response:

```json
{"schemaVersion":1,"slug":"lildooby-signal-strip","commit":"<40-character review commit>"}
```

## 3. Capability call

MCP Streamable HTTP (stateless) at `POST https://signal-strip-mcp.onrender.com/mcp`, JSON-RPC 2.0.

List tools:

```bash
curl --fail --silent --show-error \
  --request POST https://signal-strip-mcp.onrender.com/mcp \
  --header "content-type: application/json" \
  --header "accept: application/json, text/event-stream" \
  --data '{"jsonrpc":"2.0","id":1,"method":"tools/list","params":{}}'
```

Expected: five tools — `list_inventory`, `get_package_details`, `book_slot`, `get_booking_status`, `get_payment_instructions`.

Call `list_inventory`:

```bash
curl --fail --silent --show-error \
  --request POST https://signal-strip-mcp.onrender.com/mcp \
  --header "content-type: application/json" \
  --header "accept: application/json, text/event-stream" \
  --data '{"jsonrpc":"2.0","id":2,"method":"tools/call","params":{"name":"list_inventory","arguments":{}}}'
```

Expected success: JSON text payload with `count: 18` and an `items` array (first item `booth-ax1`, price 5 USDC), plus a `stub_notice` that inventory is static.

Create a booking intent:

```bash
curl --fail --silent --show-error \
  --request POST https://signal-strip-mcp.onrender.com/mcp \
  --header "content-type: application/json" \
  --header "accept: application/json, text/event-stream" \
  --data '{"jsonrpc":"2.0","id":3,"method":"tools/call","params":{"name":"book_slot","arguments":{"package_id":"booth-ax1","buyer_handle":"reviewer-test"}}}'
```

Expected success: booking object with `status: "pending_payment"`, a `booking_id` like `ss-xxxxxxxx`, and a `stub_notice` that this is intent-only (no payment captured).

Safe failure response — unknown package:

```bash
curl --fail --silent --show-error \
  --request POST https://signal-strip-mcp.onrender.com/mcp \
  --header "content-type: application/json" \
  --header "accept: application/json, text/event-stream" \
  --data '{"jsonrpc":"2.0","id":4,"method":"tools/call","params":{"name":"get_package_details","arguments":{"package_id":"nope"}}}'
```

Expected: error payload with `isError: true` and message `Unknown package_id 'nope'.` plus hint to call `list_inventory`.

All tokens, user data, and production identifiers are redacted. `buyer_contact` is optional and was omitted above.
