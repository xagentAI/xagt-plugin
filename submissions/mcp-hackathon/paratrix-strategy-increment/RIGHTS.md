# Rights, licenses, and data provenance

Project: Strategy Increment
Submitter: Kunson (individual)
Submission slug: paratrix-strategy-increment
Date: 2026-09-25
Maintainer and publisher: [karpak-labs](https://github.com/karpak-labs)
Source: [karpak-labs/strategy-increment](https://github.com/karpak-labs/strategy-increment)
Contact: [GitHub Issues](https://github.com/karpak-labs/strategy-increment/issues)

## Submission declaration

The submitter confirms ownership of, or sufficient authorization for, the source code, dependencies, service, data, branding, and other materials included in this submission.

Subject to the official program terms, the submitter authorizes X-Agent to retain, reproduce, audit, test, archive, and publish the submitted program artifact for judging, fraud prevention, dispute handling, ecosystem submission, and post-award accountability. Closing the pull request, deleting a fork, or deleting the external repository does not revoke the official archive rights attached to an accepted and rewarded entry.

Third-party components and data retain the licenses and rights described below. The first-party MIT grant does not relicense them. No additional restrictions are asserted on the first-party materials.

## First-party materials

First-party code, documentation, and example-generation code are distributed under the [MIT License](LICENSE), with `Copyright (c) 2026 karpak-labs`. This covers the project's own calculation engine, API, workbench, data adapters, storage, reproduction tools, and tests.

## Third-party components

Python test and offline-verification dependencies are pinned in `source/uv.lock`. Worker dependencies and build tools have separate lockfiles under `source/workers/`; see the [deployment guide](source/docs/DEPLOYMENT.md). Dependencies retain their own licenses. The [third-party inventory](source/third-party/README.md) records components and how they are used.

The AIMM reference revision is [`dd711507690450e9c4c9b170829b01f1e7d7f1b6`](https://github.com/olaxbt/ai-market-maker/tree/dd711507690450e9c4c9b170829b01f1e7d7f1b6). Its upstream license is GNU Affero General Public License v3; the full text is retained in [AIMM-LICENSE.txt](source/third-party/AIMM-LICENSE.txt). AIMM is not an application runtime dependency, and its source is not covered by this project's first-party MIT license.

## Example data

| Material | Source and use |
| --- | --- |
| Three AIMM equity JSONL files | Local backtest outputs from a pinned engine revision, used to demonstrate and verify the input adapter; revision, configuration, point counts, and hashes are recorded in the [manifest](source/fixtures/recorded/aimm/manifest.json) |
| AIMM research summary | Retains run configuration, results, and provenance including selected execution prices; see the [run record](source/docs/evidence/aimm-feasibility-evidence.json) |
| Constructed teaching examples | Generated deterministically by this project to verify duplicate-baseline, cash-control, missing-day, and return/drawdown tradeoff behavior |
| User imports | Supplied by the user as independent experiment inputs; not distributed with the source repository |

The AIMM backtests reference the upstream repository's daily BTC/USDT CSV. This repository distributes equity outputs and provenance summaries, not the original market-price CSV. The first-party MIT license does not change existing rights in upstream materials or data. See [sample documentation](source/fixtures/README.md) for time semantics and adaptation.

Competition submission is also subject to the organizer's review and archival terms. See the [release guide](source/docs/RELEASE.md) for the review and archival procedure.
