# T0521 · x402 free-trial fix deploy + resubmit · 2026-07-11

## Status

**Listing under review** (`approvalDisplayStatus=2`) · remark: `AI 质检建议通过`

## What changed

| Step | Evidence |
|---|---|
| Code | `agent-acceptance-gate@543abe8` — unpaid POST always 402 unless `X402_FREE_TRIAL=true` |
| Deploy | Worker Version ID `2aa22173-50ee-4e35-94f5-55af1d50e699` → `api.leolabs.me` |
| Live catalog | `billing.free_trial` = disabled |
| Unpaid POST | HTTP **402** |
| x402-check | **10/10** listed endpoints `valid=true` with `--body '{}'` |
| Activate | `submitApproval.approvalStatus=2 success=true` → under review |

## Commands used

```bash
npm run deploy:worker
onchainos agent x402-check --endpoint <each> --body '{}'
onchainos agent activate --agent-id 3977 --preferred-language zh-CN
```

## Discipline

Under review freeze: **no fragmented service update/activate** until terminal status.

## Next

1. Wait for listing terminal (email watcher now covers Junk/All Mail)
2. On approve: screenshot + English contest post + Google form (Leo publish gate)
3. Do **not** set `X402_FREE_TRIAL=true` until after listing passes (optional marketing later)

## Note on CLI

`onchainos agent x402-check` **without** `--body` still hits GET sample → false 200 failure. Always use `--body '{}'`.
