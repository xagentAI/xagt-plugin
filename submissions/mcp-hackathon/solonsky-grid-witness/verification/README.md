# Verification evidence

Review commit: `9102fa95b06ec90b43d7c8dc397e2a03fbd0bf35`
API origin: https://bestdeeplearning-grid-witness.hf.space
Authentication: none. Inputs below are entirely synthetic.

## Health and proof

```sh
curl --fail --silent --show-error https://bestdeeplearning-grid-witness.hf.space/health
curl --fail --silent --show-error https://bestdeeplearning-grid-witness.hf.space/.well-known/xagent-verification.json
```

Health must return HTTP 200 JSON status ok and the review commit. The proof must return schemaVersion 1, slug solonsky-grid-witness and that same commit. HTML or a missing version is a failed check.

## Capability call

```sh
curl --fail --silent --show-error https://bestdeeplearning-grid-witness.hf.space/v1/inspect-plan -H 'Content-Type: application/json' -d '{"bits":[1,1,1,0,0,0]}'
```

Expect cost 18, A_accepted true, B_accepted false, linear_false_positive true and a positive voltage-violation witness at load scale 6/5. Values are per unit, costs synthetic. This is a computed operating-point violation, not proof of global AC infeasibility.

```sh
curl --fail --silent --show-error https://bestdeeplearning-grid-witness.hf.space/v1/compare-budget -H 'Content-Type: application/json' -d '{"budget":19}'
curl --fail --silent --show-error https://bestdeeplearning-grid-witness.hf.space/v1/compare-budget -H 'Content-Type: application/json' -d '{"budget":20}'
```

19: no accepted operating point within budget. 20: cheapest accepted cost 20 and plans [1,1,0,1,1,0], [1,1,1,0,0,1]. Synthetic cost units are not monetary amounts.

## Safe error

```sh
curl --silent --show-error -i https://bestdeeplearning-grid-witness.hf.space/v1/inspect-plan -H 'Content-Type: application/json' -d '{"bits":[true,true,true,true,true,true]}'
```

Expect HTTP 400 and error invalid_request. Boolean is not an integer upgrade bit.

## Reproducibility

From source/: `python -m pip install -r requirements-test.txt && python -m unittest discover -v`. The source has sixteen tests including closed-form numerical reference, residual validation, all 64 catalogue plans, 512 encoded surrogate states, API errors and budget boundaries. requirements-test.lock records the local test environment; README pins platform Gradio SDK 6.27.0.

The accompanying public JSON evidence records actual requests/responses and source hashes. The deployed HF snapshot is compared with GitHub at the reviewed SHA. Health self-reporting does not by itself prove provenance, completeness or correctness. The free host may cold start; no uptime SLA is claimed.

## Recorded run

Verified on 2026-09-12 at 02:46 UTC: seven live API checks passed. HF deployed snapshot `7fac9d7a378342a06c6a8c4ec9914f5efd6f35ea`; review commit above. All thirteen source files matched byte-for-byte across local copy, GitHub and the pinned HF snapshot. The online official validator passed all six reported gates. See live-api.json, github-source-audit.json, hf-source-audit.json, tests.txt and official-online-check.txt. These are receipt-free technical results, not judging approval.
