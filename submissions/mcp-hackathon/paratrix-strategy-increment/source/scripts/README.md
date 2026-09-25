# Local verification, Worker builds, and packaging

Run these commands from `source/`:

- `python scripts/smoke.py --base-url http://127.0.0.1:8787`: exercise the complete workflow over real HTTP; output defaults to the ignored `runtime/` directory.
- `python -m app.reproduce runtime/smoke-evidence.json`: reproduce evidence with the Python standard library and no network access.
- `python scripts/build_worker.py`: build an isolated local Cloudflare Worker project in `runtime/worker-bundle`; this command does not deploy or access a Cloudflare account.
- `python scripts/package_submission.py /tmp/new-review-directory`: create a complete review copy from a clean Git checkout. The packager combines repository `submission-config.json` with Git HEAD to generate the review package's `submission.json`, and excludes installed dependencies, caches, runtime data, and credentials. The destination directory must not exist; the independent source repository must not contain a root `submission.json`.

Worker release builds require a clean Git checkout and a public HTTPS origin. Build configuration and deployment commands are in [deployment](../docs/DEPLOYMENT.md); publication and review-package steps are in the [release guide](../docs/RELEASE.md).

## Local Worker stress and persistence checks

`smoke_worker.py --phase before-restart` creates disposable local sessions, checks concurrent history classification and quotas, and round-trips 5,000-point experiments. Restart the same local Worker, then use `--phase after-restart` to verify unchanged history and evidence. It accepts only local HTTP origins. Cookie state is private and stays under ignored `runtime/`; see [validation](../docs/VALIDATION.md).
