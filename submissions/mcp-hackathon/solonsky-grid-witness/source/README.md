---
title: Grid Witness
emoji: 🔎
colorFrom: indigo
colorTo: blue
sdk: gradio
sdk_version: 6.27.0
app_file: app.py
python_version: 3.12
license: mit
---
# Grid Witness

A deterministic capability for an AI agent to challenge an optimistic grid-upgrade plan with numerical evidence. It compares exact rational lossless LinDistFlow screening against a backward/forward-sweep AC operating point and independently recomputed current, power, slack and limit residuals.

**Scope:** one fixed synthetic six-line radial chain, three load levels, 64 upgrade plans. Not real network data, not E.ON technology, not a quantum algorithm or an industrial engineering certificate. A returned operating point violating a limit is not a proof that all AC solutions are infeasible.

## Try the counterexample

Send `{"bits":[1,1,1,0,0,0]}` to `POST /v1/inspect-plan`. The cost-18 plan passes the lossless screen but its AC operating point violates the minimum-voltage limit at scale 1.2. `POST /v1/compare-budget` with `{"budget":20}` finds two cost-20 plans whose computed operating points pass all three scenarios. Budget 19 finds none. These are arbitrary synthetic cost units, not EUR or USD.

## API

- `GET /health`: versioned service health (503 if SOURCE_COMMIT not a 40-character SHA).
- `GET /.well-known/xagent-verification.json`: submission slug and same review commit.
- `GET /v1/benchmark`: full specification, summary and limitations.
- `POST /v1/inspect-plan`: exactly one `bits` field with six integer binary values. Booleans, strings, floats and extra fields are rejected.
- `POST /v1/compare-budget`: exactly one integer `budget` from 0 to 27.

POST requests require `application/json` and at most 2048 bytes. Invalid requests return HTTP 400 and a stable `invalid_request` error. Unknown routes return 404. Calls enumerate a bounded catalogue cached in memory; no unconstrained network input, arbitrary execution or model calls. No dedicated service-level rate limit; hosting provider limits and cold starts apply. Request concurrency is handled by Gradio/FastAPI; returned data is copied to prevent cache mutation. No availability SLA.

## Reproduce

Python 3.12+:

```sh
python -m venv .venv
.venv/bin/pip install -r requirements-test.txt
.venv/bin/python -m unittest discover -v
.venv/bin/python benchmark.py
```

`requirements-test.lock` records the locally tested dependency set. The numerical benchmark itself uses only the Python standard library. Sixteen tests cover the closed-form one-line case, power conservation, independent residual checks, nonconvergence, all 64 plan outputs and 512 encoded surrogate states, API validation and cost boundaries.

For the Gradio demo, install `gradio==6.27.0` and `spaces` in addition to `requirements.txt`, then set `SOURCE_COMMIT` to the source commit and run `python app.py`. On Hugging Face Spaces the platform supplies Gradio and spaces; do not add conflicting pins to requirements.txt.

## Deploy

Create a public Gradio Space on a free ZeroGPU allocation, set its **public variable** SOURCE_COMMIT to the reviewed GitHub SHA, and upload exactly that commit's files with `hf upload NAMESPACE/SPACE . --type space`. No secrets are needed. The optional hosting diagnostics handler declares a one-second ZeroGPU scheduler probe to meet free-tier hosting requirements; **all grid calculations run on CPU** and never allocate a GPU. CPU Basic creation currently requires a paid Hugging Face plan, so no paid hardware was selected.

The commit is provided at deployment rather than embedded in its own source. Verify the deployed files against the review commit as well as checking health/proof. Source commit changes require updating the deployment variable and archiving fresh verification evidence.

## Mathematical model and provenance

Adapted from a synthetic classical demonstrator prepared for Alex SOLONSKY before this hackathon API. `benchmark.py` preserves that original model. It includes an exhaustively verified QUBO encoding only to check its equivalence to the lossless surrogate; no quantum computation is performed. Grid Witness adds the HTTP/agent capability, strict validation, bounded-budget comparison, UI and API tests.

Bus 0 is 1+0j slack; edges 0–1 through 5–6 have impedance 0.01+j0.006 p.u. Upgrade bits halve impedance without changing ampacity 1 p.u. Six constant PQ loads are 0.08+j0.04 p.u., multiplied by 0.6, 1, 1.2. Squared voltage bounds are 966304/1000000 and 11025/10000. Costs are [7,6,5,4,3,2]. No renewable uncertainty, contingencies, phase unbalance, topology control, independent external solver, AC uniqueness/global optimum proof or quantum advantage claim.

## Privacy and third parties

Only six binary decisions or an integer budget enter the capability. Inputs and outputs are not saved by the application; no database, uploads, analytics, LLM calls or outbound requests occur during scientific computation. Hugging Face serves the app and may keep platform access logs. Gradio assets/runtime and its optional hosting diagnostics contact the platform. Do not send personal or operational network data.

Source: MIT. Dependencies: FastAPI MIT, Starlette BSD-3-Clause, Pydantic MIT, Uvicorn BSD-3-Clause, Gradio Apache-2.0, Hugging Face spaces Apache-2.0, HTTPX BSD-3-Clause (test only). See package distributions for complete transitive notices. No pretrained models or external datasets.

Builder: Alex SOLONSKY (Aleksei Solonskii). Support: open an issue in this repository. No connection to the cancelled EvidenceDesk project or private Life CP code.
