# Scoring (deterministic, 0-100)

- Schema Quality 25: missing 2xx schema = major penalty.
- Documentation 15: missing/short description, missing param docs.
- Consistency 15: minus 5 per critical/high issue.
- Error Handling 15: missing 4xx/5xx docs penalized.
- Reliability 15: pass-rate of live safe tests (neutral 10 without tests).
- Agent Usability 15: weak operationId, ambiguous param names.

Severity: critical/high/medium/low/info. Every penalty emits an issue with endpoint + suggested repair, so the UI can explain WHY.
