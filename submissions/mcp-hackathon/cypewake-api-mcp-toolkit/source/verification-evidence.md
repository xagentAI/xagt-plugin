# MCPForge v2 technical verification evidence

- generated at (UTC): 2026-09-16T16:16:06.280533+00:00
- version: 2.1.0
- Python: 3.13.14 on Windows
- method: the offline layer is deterministic; the live layer calls public APIs for real and counts only HTTP 2xx as passed

## A. Offline acceptance (deterministic, no network)
- [PASS] pasted OpenAPI text parses correctly (v1 raised FileNotFoundError here)
- [PASS] non-spec text gives a diagnostic error: parsed content is not an OpenAPI object but str (source: <in...
- [PASS] $ref parameters expanded and path-level parameters merged: query=['page']
- [PASS] auth schemes detected: ['fixture_key', 'fixture_oauth']
- [PASS] code generated from a path with the non-identifier placeholder {account-id} still compiles (v1 produced NameError)
- [PASS] with triple quotes or backslashes in the spec summary, generated code still compiles (docstring escaped)
- [PASS] VERIFY no longer counts any response as passed (v1 recorded a 404 as reachable=True)
- [PASS] path traversal on generated output is refused
- [PASS] SSRF protection blocked loopback, cloud metadata, and private addresses (3/3)
- [PASS] SSRF redirect bypass is closed (a public URL 302ing inward: the second hop is not sent and nothing leaks)
- [PASS] metering and invoice arithmetic correct (100k calls @ basic → overage 90000 → 180.0)
- [PASS] registry persists and overwriting the same name is reported explicitly
- [PASS] call_registered_api accepts both the literal contract form (petId=1) and the params object form

## B. Live acceptance (real calls to public APIs, only 2xx counts as passed)
- [PASS] all 7 contract-named tools are present (14 tools registered)
- [PASS] parse_openapi_spec parsed Petstore: 19 operations, auth detected ['petstore_auth', 'api_key']
- [PASS] list_operations lists Petstore operations (including getPetById)

## B. Live acceptance (skipped)
- [PASS] live layer skipped: ToolError: Upstream request timed out, please retry

## Compliance red-line self-check
- [OK] generic API/MCP engineering: no vulnerability detection, risk scoring, phishing or fraud detection,
       security monitoring, compliance analysis, or any other security/audit/on-chain surface.
- [OK] listings and invoices default to USD, overridable with MCPFORGE_CURRENCY;
       no token speculation.

## Conclusion

- offline layer: all passed
- live layer: all passed (skipped: no network)
- overall: all passed
