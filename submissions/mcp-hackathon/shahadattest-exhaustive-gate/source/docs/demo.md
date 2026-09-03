# Demo (3-5 min)

1. `docker-compose up --build` (frontend :8102, gate :8100, CRM :8101).
2. Open dashboard, click **Run Demo: exactly-N**.
3. Page 1: 100 records, continuation YES. Claim "exactly 100" -> UNPROVEN / PAGINATION_NOT_EXHAUSTED.
4. Click **Fetch Next Page** x3 (347 records, 4/4, snapshot stable).
5. Verify "exactly 347" -> PROVEN + proof certificate. Hero: 100 ❌ -> 347 ✅.
6. Other scenarios: NONE+timeout (UNPROVEN/UNRESOLVED_FAILURE), cheapest product (UNPROVEN then PROVEN prod_008 price 3), snapshot_change (UNPROVEN/SNAPSHOT_CHANGED).
