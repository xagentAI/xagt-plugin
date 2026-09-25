# Third-party components and provenance

First-party code and documentation use the [MIT License](../../LICENSE). This inventory records software dependencies and reference materials included with the repository. Third-party materials retain their own licenses and source identification.

## Recorded AIMM simulations

| Item | Details |
| --- | --- |
| Upstream | [OlaXBT/AIMM](https://github.com/olaxbt/ai-market-maker) |
| Pinned revision | `dd711507690450e9c4c9b170829b01f1e7d7f1b6` |
| License | GNU Affero General Public License v3; [full text](AIMM-LICENSE.txt) |
| Use | Read recorded local simulated equity; the application neither installs nor executes AIMM |
| Included materials | Three equity JSONL files, configuration/hash manifest, and run provenance summary |
| Data documentation | [Sources and timestamp adaptation](../fixtures/README.md) |

The upstream market-price input was `data/ohlcv/BTC_USDT_1d.csv`; that CSV is not included here. The run summary retains selected execution prices and metrics. The first-party MIT license does not grant new rights in upstream materials or data.

## Python application and verification dependencies

The following application-library licenses come from installed package metadata. `uv.lock` records the complete CPython test dependency set and platform hashes. `workers/uv.lock` pins the host-side build tools; `workers/pylock.toml` pins the packages loaded by the Pyodide Worker runtime. Behavior tests use the same FastAPI and Pydantic versions as the Worker. The host-side build-tool environment is separate from deployed application dependencies. The offline reproduction CLI itself uses only the standard library.

| Package | CPython tests | Worker runtime | License |
| --- | --- | --- | --- |
| annotated-doc | 0.0.5 | 0.0.5 | MIT |
| annotated-types | 0.8.0 | 0.8.0 | MIT |
| anyio | 4.15.1 | 4.15.1 | MIT |
| fastapi | 0.141.1 | 0.141.1 | MIT |
| h11 | 0.16.0 | Not used | MIT |
| idna | 3.20 | 3.20 | BSD-3-Clause |
| pydantic | 2.12.5 | 2.12.5 | MIT |
| pydantic-core | 2.41.5 | 2.41.5 | MIT |
| starlette | 1.7.0 | 1.7.0 | BSD-3-Clause |
| typing-extensions | 4.16.0 | 4.16.0 | PSF-2.0 |
| typing-inspection | 0.4.4 | 0.4.4 | MIT |

## Worker runtime and build tools

Worker Python dependencies are pinned by `workers/pyproject.toml`, `workers/uv.lock`, and `workers/pylock.toml`. Wrangler and its transitive npm dependencies are pinned by `workers/package.json` and `workers/package-lock.json`.

| Component | Version | License | Role |
| --- | --- | --- | --- |
| fastapi | 0.141.1 | MIT | Shared HTTP application in the Python Worker |
| workers-py | 1.17.4 | MIT | Python Worker build/development tooling |
| workers-runtime-sdk | 1.9.0 | MIT | Python interfaces to Worker requests, ASGI, bindings, and Durable Objects |
| wrangler | 4.140.0 | MIT OR Apache-2.0 | Local Workers runtime and deployment tooling |

The Worker tool licenses above were checked against installed package metadata. Dependencies are installed through standard package tools; installation directories are excluded from the source delivery. Local development tools are managed by the `dev` group in `uv.lock`. Cloudflare platform services and the service operator's account are configured separately from the first-party MIT code.
