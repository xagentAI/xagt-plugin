# Why Abstain uses a fail-closed receipt chain

Abstain sits before execution. A useful answer must do more than say yes or no: it must prove which evidence and rules produced the decision, survive concurrent serverless requests, and refuse when required evidence cannot be trusted.

## The problem

A conventional risk endpoint can quietly fail in several dangerous ways:

- A missing data source becomes a default value that accidentally passes.
- Two serverless instances read the same chain head and both write the same next sequence.
- A caller invents a fresh signal identifier and bypasses replay protection.
- A deployment silently falls back to memory and loses its history on a cold start.
- A stale deployment reports internally consistent metadata while running the wrong source revision.

Any one of these makes the audit trail look healthy while weakening the decision it is meant to prove.

## The approach

Abstain separates evidence collection, deterministic decision logic, and durable recording:

```text
                         resolve latest covered date
                                    |
Proposal -> Nexus fan-out -> validated evidence -> ten pure checks
                                                    |
                                  EXECUTE / ABSTAIN / NO_TRADE
                                                    |
                           bind decision to observed chain snapshot
                                                    |
                              SHA-256 seal + atomic Redis CAS
                                                    |
                                           return response
```

The receipt is committed before the API responds. If Redis is unavailable or contention cannot be resolved, the endpoint returns 503 with `receipt_written:false`; it does not return an unrecorded verdict.

## Fail-closed evidence

Each Nexus payload crosses a validation boundary before it reaches the gate. Abstain checks required object shapes, finite numeric values, allowed enum values, requested symbol and date, prior open interest, positive equity, strictly increasing equity timestamps, and a non-empty equity curve. The gate also rejects a signal timestamp that lies in the future.

Unavailable data remains distinguishable:

- `absent` means Nexus has no published datum.
- `failed` means the request or parsing failed.

Individual checks can report `SKIPPED` when their input is unavailable, but `DATA_GAP` converts required missing evidence into an `ABSTAIN`. This keeps receipts descriptive without letting uncertainty become authorization.

## Deterministic decisions

The gate receives all inputs explicitly: evidence, policy, proposal, account equity, current time, as-of date, and previously seen signal identifiers. It performs no I/O and reads no ambient clock.

This design gives the live API and offline replay the same decision path. It also makes threshold, replay, and no-lookahead tests exact instead of probabilistic.

A `HOLD` signal does not bypass the gate. Abstain evaluates what an agent **proposes**, not what the strategy happens to be emitting, so a proposal with no directional signal behind it fails the `SIGNAL_SUPPORT` check and the verdict is `ABSTAIN` with all eleven checks recorded. Earlier receipts in the live chain carry the legacy `NO_TRADE` verdict from before this change; they remain valid links and verify normally.

## Hash-linked receipts

Each receipt contains its body, one-based sequence number, and the preceding receipt hash:

```text
hash(n)      = sha256(canonical({ body, seq, prev_hash }))
prev_hash(1) = sha256:000000...000
prev_hash(n) = hash(n - 1)
```

Canonical JSON recursively sorts object keys and preserves array order. Verification checks sequence continuity, links, and content hashes, returning the first divergent sequence rather than a generic invalid result.

The chain detects alteration; it does not hide data. Reads are public by design so an independent reviewer can recompute every link.

## Concurrency and decision freshness

An atomic append alone is insufficient. It can protect the hash chain while still committing a decision built from stale duplicate state.

Abstain binds each decision to the exact receipt snapshot used by the gate:

1. Evaluate against snapshot head `H`.
2. Seal the candidate as the successor of `H`.
3. Atomically compare the current Redis head with `H` and append only if they match.
4. If another writer won, reload the chain, re-evaluate the stateful duplicate check, reseal, and retry.

The Redis Lua script makes the compare-and-append operation indivisible. A stale writer cannot quietly land against a newer head. After 16 unsuccessful attempts, the API returns `chain_contended` and writes nothing.

## Durable production behavior

Replay mode intentionally uses process-local memory for zero-credential testing. Production is different: when `VERCEL_ENV=production`, the write endpoint refuses every evaluation unless a complete Redis credential pair produced a durable store.

`/health` remains dependency-free so liveness does not depend on Nexus or Redis. `/v1/ready` carries dependency and durability state. These endpoints answer different questions:

- `/health`: is this deployment process alive, and which source revision is it?
- `/v1/ready`: can this deployment perform durable evaluations now?

## Trade-offs

- **More reads under contention:** a losing writer reloads the chain before retrying. This favors correctness over peak write throughput.
- **Append-only growth:** receipts are not deleted without invalidating later links. Rate limits bound growth speed but do not cap total history.
- **Public evidence:** receipts expose decision evidence and hashes. Secrets and raw credentials must never enter receipt payloads.
- **Redis dependency in production:** durable writes stop when Redis stops. This is intentional; ephemeral success would be a false claim.
- **No order execution:** Abstain proves authorization or refusal but delegates execution to another system.

## Alternatives rejected

### Process-local storage in production

Serverless instances do not share memory and can reset independently. A green response from an ephemeral instance cannot support a durable evidence claim.

### Check-then-write without compare-and-set

Two writers can observe the same head and create competing successors. Retrying only after the write does not repair a fork that was already accepted.

### Caller-supplied signal identifiers

A caller could assign a new identifier to unchanged evidence and bypass duplicate protection. The server derives identity from the Nexus signal timestamp and requested market.

### Treating malformed evidence as zero

Zero can legitimately pass several threshold comparisons. Malformed or mismatched evidence is therefore represented as failed data and carried into `DATA_GAP`.

## Related

- [HTTP API and configuration reference](reference-api.md)
- [Getting-started tutorial](tutorial-getting-started.md)
- [Testing and deployment how-to](how-to-test-and-deploy.md)
