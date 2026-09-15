# DRAFT — current editorial release verification

The reviewed source is 18d0eac794d0075df3f763bd2a442370e03f02fd. All 27 tracked files are included in source/, copied and compared byte-for-byte with exact Git blobs (2,217,942 bytes). source-manifest.json records paths, Git blobs, SHA-256 values and sizes. The editorial interface includes the original selected illustration and three locally served font files, with their notices and provenance; THIRD_PARTY.md inventories the additions.

## Current checks

All 32 Node tests passed with zero failures on the final main source. Wrangler 4.131.1 dry-run succeeded: 72.39 KiB bundle / 20.94 KiB gzip. Current local records and captured test/build output are included under verification/.

Public audit 2026-09-14T08:53:23.696Z to 2026-09-14T08:53:40.328Z: 24 HTTP requests, 52 assertions passed, zero failed. Exact requests, observed statuses, source comparisons and limits are in verification/current-public-checks.json. These are point-in-time observations of the published version.

All 10 current public browser checks passed: the editorial homepage and original illustration, CTA, successful CSV transform, JSON disclosure, edit invalidation, typed error, reset, readable guide, live status with exact source SHA, and home navigation. The 320 px mobile check was performed on the earlier local candidate; it is not relabeled as a fresh public mobile check. Public HTML/CSS/JS/PNG/WOFF2 bytes matched that checked candidate.

- [current-public-checks.json](current-public-checks.json)
- [current-deployment.json](current-deployment.json)
- [current-local-checks.json](current-local-checks.json)
- [schemabridge-editorial-tests-sep14.txt](schemabridge-editorial-tests-sep14.txt)
- [schemabridge-editorial-build-sep14.txt](schemabridge-editorial-build-sep14.txt)
- [current-browser-checks.json](current-browser-checks.json)

## Health and deployment proof

Repeat these unauthenticated health and proof calls. Both must return HTTP 200; health must report status ok and the source commit below, and proof must report schemaVersion 1, slug fenix-schemabridge and the same commit.

```sh
curl -q --silent --show-error --include --max-time 30 --header 'Cookie:' --header 'Authorization:' 'https://schemabridge.wiaikit.com/health'
curl -q --silent --show-error --include --max-time 30 --header 'Cookie:' --header 'Authorization:' 'https://schemabridge.wiaikit.com/.well-known/xagent-verification.json'
```

```json
{
  "expectedHealth": {
    "status": "ok",
    "commit": "18d0eac794d0075df3f763bd2a442370e03f02fd"
  },
  "expectedProof": {
    "schemaVersion": 1,
    "slug": "fenix-schemabridge",
    "commit": "18d0eac794d0075df3f763bd2a442370e03f02fd"
  }
}
```

The expected values above are assertions, not fabricated response logs. Current observed responses are retained in current-public-checks.json. Use curl.exe in PowerShell.

## Capability success and safe failure

From the entry directory (the parent of source/), run these commands without account credentials. The request files contain only synthetic data. Use curl.exe in PowerShell.

```sh
curl -q --silent --show-error --include --max-time 30 --header 'Cookie:' --header 'Authorization:' --header 'Content-Type: application/json' --request POST --data-binary '@source/fixtures/csv-request.json' 'https://schemabridge.wiaikit.com/v1/transform'
curl -q --silent --show-error --include --max-time 30 --header 'Cookie:' --header 'Authorization:' --header 'Content-Type: application/json' --request POST --data-binary '@source/fixtures/invalid-request.json' 'https://schemabridge.wiaikit.com/v1/transform'
```

The first call must return HTTP 200 and exactly the JSON object in source/fixtures/csv-expected.json: two output rows, quantities 7 and 0, boolean availability true and false, and four converted cells. The second must return HTTP 422 with ok false, error.code VALIDATION_FAILED, error.details.totalErrors 2 and two field errors; no partial output data is returned. This checks invalid numeric and boolean values without malformed traffic or real user information. Observed final responses are recorded in final-public-sep15.json.

## Final approved-packet recheck, 15 September

The submitted source snapshot passed all 32 tests again at 07:53:51 UTC. The local dry-run build with locked Wrangler 4.131.1 passed at 07:54:25–07:54:31 UTC: 72.39 KiB / gzip 20.94 KiB. The build used the existing locked toolchain installation against this source snapshot, not a new dependency installation. Its first attempt encountered a Windows filesystem sandbox denial; the authorized local retry passed. No deployment occurred. See final-tests-sep15.txt and final-build-sep15.txt. Generated build output and Wrangler working files are excluded from the submitted entry.

## Reproduction and version mapping

```text
npm ci --registry=https://registry.npmjs.org/
npm test
npm run build
npm run demo
npm start
```

Cloudflare Worker fenix-schemabridge: version d181e389-117e-45f0-9516-56e9a96c0eb0, deployment 5e9f28ff-e340-457d-8154-65388ef55f50, 100% traffic, deployed 2026-09-14T08:51:20.584213Z. See verification/current-deployment.json. Operator control-plane observations and public byte comparisons are separate evidence; configured source metadata is not signed build attestation.

The organizer confirmed on 15 September 2026 at 06:23 UTC that public endpoints must identify the source commit used for the submitted and deployed service; it does not need to match the final PR head in the X-Agent submission repository. The published sourceRepository/reviewCommit values therefore remain bound to the source SHA above. Submit the corresponding source/ snapshot and source-manifest.json, and compare the submitted source files with that manifest. The organizer reviews and merges entries individually. The official PR has not been created; its eventual head is a separate submission identifier, not a replacement for the service source SHA. This version-mapping clarification is resolved.

## Official validator

```text
node scripts/validate-submission.mjs --dir submissions/mcp-hackathon/fenix-schemabridge
node scripts/validate-submission.mjs --dir submissions/mcp-hackathon/fenix-schemabridge --online
```

The saved official validator has SHA-256 d2eb01d7d628cf1b346cf7bf10f608005bfaff1028d61f9d210db550144ecfb7. On 15 September its bytes were checked against the current official GitHub blob a3f55d798827b7f8094967066d9ee253af528bc4 and matched; its upstream main commit was not separately pinned. Final approved-packet invocation records and exact digest are stored outside the entry in READINESS.md, package-audit.json and validation-offline/online.json. Earlier validation history remains explicitly dated. A validator pass does not register or submit the entry, decide eligibility, or establish an award.

## Review conditions and limits

The organizer replied on 14 September that SchemaBridge appears suitable for Open Innovation subject to technical review. The official PR must include complete runnable code, dependencies/lockfiles, secret-free configuration examples, setup instructions and tests. Free hosting is acceptable during 20 September–1 October. The 19 September cutoff hour/timezone remains unannounced. First prize is 500 USDT plus 15,000 X-Points for a winning team; network and payment timing are confirmed after final review, merge and acceptance archive.

These checks do not establish continuous review-period availability, load capacity, provider retention or a hosting CPU guarantee. No future award or payment is assumed. Use synthetic or non-sensitive data. The visual release changes presentation and static-asset delivery; its scope and any untested scenarios are recorded in the current local/public/browser evidence.

Aleksandr Parkhomenko expressly approved the completed RIGHTS.md declaration on 2026-09-15, including the disclosed third-party conditions. Registration, official community membership and the official contest PR remain incomplete. No award, paid assignment or payment is established by this packet.
