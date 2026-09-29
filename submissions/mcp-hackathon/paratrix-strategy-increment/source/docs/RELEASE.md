# Release and submission

The independent `karpak-labs/strategy-increment` repository is the product's source of truth. The contest directory `submissions/mcp-hackathon/paratrix-strategy-increment/` contains a complete review copy generated from the validated product version.

## Bind the release

Review and commit the complete source, configuration, dependency locks and tests. Build from a clean checkout using the [Cloudflare deployment instructions](DEPLOYMENT.md). The production builder binds the actual 40-character Git HEAD and the source digest. It refuses uncommitted source or an invalid public HTTPS origin.

The business API, health endpoint and standard verification endpoint must share the same HTTPS origin. `/health` returns `status: ok` and the source commit. `/.well-known/xagent-verification.json` returns the schema version, project slug and the same commit.

The [public health endpoint](https://strategy-increment.raspy-boat-dbb0.workers.dev/health) and [deployment proof](https://strategy-increment.raspy-boat-dbb0.workers.dev/.well-known/xagent-verification.json) expose the deployed source revision. The packager derives `reviewCommit` from the clean source checkout and creates `submission.json` in the generated review package. This generated manifest is not tracked in the independent source repository.

## Prepare review materials

| File | Purpose |
| --- | --- |
| `SUBMISSION.md` | Capabilities, review flow, service entry points and support |
| Generated `submission.json` | Project identity, public source repository, review commit and API / health / proof URLs |
| `RIGHTS.md` | Submitter identity, material rights, third-party licensing and review/archive authorization |
| `source/` | Complete application, build configuration, dependency locks and tests |
| `verification/` | Repeatable requests and sanitized evidence with explicit validation scope |

PRs, primary documentation, API errors, logs and code comments use English. The workbench uses Chinese presentation text. Original third-party material and reproduction fixtures retain their original language and bytes. [RIGHTS.md](../../RIGHTS.md) describes the submitter, licensing and material provenance using the [official rights template](https://github.com/xagentAI/xagt-plugin/blob/239140cc04dc82a121e9c31199bc8a12b510e130/submissions/RIGHTS_TEMPLATE.md).

## Generate the review copy

Run from the independent repository root. The destination must not exist:

```sh
python3 source/scripts/package_submission.py /tmp/xagt-review/paratrix-strategy-increment
```

The packager adds the manifest using Git HEAD and the public service origin. It excludes Git metadata, dependencies, caches, runtime state and generated bundles. It rejects secret-bearing files, sensitive patterns, LFS pointers and symbolic links, and checks file counts and sizes. The complete application remains under `source/`.

## Validate and submit

Run the [business API and error flows](../../verification/README.md) against the public release and independently reproduce an exported experiment. Then run in an isolated checkout of the contest validator:

```sh
npm run validate:submission -- --dir /tmp/xagt-review/paratrix-strategy-increment
npm run validate:submission -- --dir /tmp/xagt-review/paratrix-strategy-increment --online
```

Copy the validated package into its designated contest directory. The PR contains only this project's delivery. Changes to application behavior, data processing or dependencies require a new reviewed source version, deployment and verification. Each verification record identifies its source fingerprint and execution environment.

The formal contract is the [official submission guide](https://github.com/xagentAI/xagt-plugin/blob/239140cc04dc82a121e9c31199bc8a12b510e130/submissions/README.md).
