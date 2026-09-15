# Synthetic classical grid-reinforcement protocol

Executed local infrastructure prototype, 12 September 2026. **This is not an E.ON benchmark, contest submission, quantum algorithm or demonstration of quantum advantage.** The sponsor's full brief remains unavailable. The instance and voltage limit are deliberately crafted to make a tiny linear screening model reducible to an exactly checkable binary constraint and expose disagreement with AC validation.

## Reproduce

Python 3, standard library only; no packages, accounts, payment or network access required. From this directory:

```sh
python3 -m unittest discover -s . -p 'test_*.py' -v
python3 benchmark.py
```

The second command overwrites `results.json` with the complete 64-plan × 3-scenario catalogue, specification, source hash, A/B/C references and runtime. `verification.json` records the validation run supplied with this version. Results are deterministic except runtime; Python version and source SHA-256 are recorded. Runtime is local bookkeeping, not a comparison with any competing algorithm.

## Model

Six existing edges form radial chain 0–1–2–3–4–5–6. Slack voltage is 1+0j. Every other bus consumes constant complex power 0.08+j0.04 per unit times a design load scale of 0.6, 1.0 or 1.2. Each binary investment halves its edge impedance from 0.01+j0.006 to 0.005+j0.003; ampacity remains 1 per unit. Costs `[7,6,5,4,3,2]` are arbitrary units, **not euros**. Voltage magnitude limits are the square roots of 0.966304 and 1.1025. No physical base MVA or kV is selected, so no physical grid capacity claim is possible.

**A — exact finite lossless reference.** Rational LinDistFlow squared voltages include active and reactive flows but omit line losses. The current screening proxy is apparent power magnitude at assumed 1-per-unit voltage. Positive demand and radial-chain topology make the terminal bus and maximum scale binding for voltage. With investment bits `x`, the terminal squared voltage at scale 1.2 is exactly:

```
0.947584 + 0.001248 * (6*x0 + 5*x1 + 4*x2 + 3*x3 + 2*x4 + x5)
```

Thus the constructed limit is equivalent to weighted investment sum ≥15. Upper voltage and proxy thermal constraints do not bind on this instance. All 64 complete linear checks are compared against this reduced predicate, rather than assuming the reduction generalizes.

**B — numerical AC acceptance catalogue.** A backward/forward sweep solves the balanced single-phase equivalent. The independent residual calculation derives branch currents from voltage differences and impedance, then checks complex nodal power balance, nodal current balance, fixed slack voltage, voltage limits and ampacity. Flat initialization, no fallback, 500-iteration cap; voltage-change tolerance `1e-12`, absolute residual tolerance `1e-9`, floating limit tolerance `1e-10` per unit. Nonconvergence, invalid voltages or failed residuals are `unresolved`; a returned solution beyond limits is `returned_operating_point_violates_limits`. Neither status proves physical infeasibility. No external power-flow implementation or uniqueness certificate was used.

**C — complete integer QUBO reference.** Nine variables comprise six investments plus three slack bits. Enumerate all 512 states of:

```
C(x) + 28 * (6*x0 + 5*x1 + 4*x2 + 3*x3 + 2*x4 + x5 - 15 - s)^2
s = y0 + 2*y1 + 4*y2
```

Maximum feasible excess is 6, within the slack range 0–7. The penalty 28 exceeds total investment cost 27, and every nonzero integer residual incurs at least 28. A zero-penalty feasible solution exists. Expanded linear/quadratic energies are checked against the squared form for every state; projection over slack bits is checked for every investment vector. This encoding is valid only for A on this particular instance; it does not encode AC physics.

## Measured result

| Reference | Evaluated | Accepted plans | Reference cost |
|---|---:|---:|---:|
| A, exact specified lossless model | 64 plans | 14 | 18 |
| B, declared AC procedure | 192 plan/scenario checks | 10 | 20 |
| C, complete QUBO enumeration | 512 bit states | — | Minimum energy 18 |

A's sole minimum plan is `[1,1,1,0,0,0]`. B's best accepted plans are `[1,1,0,1,1,0]` and `[1,1,1,0,0,1]`. Four A-accepted plans fail the AC limit predicate. All 192 AC checks converged and passed residual checks on this run; zero were unresolved. **Cost 20 is the lowest cost accepted by this numerical procedure, not a certified global AC optimum.** The small crafted example supports only the need to keep the three references distinct.

## Validation evidence

Eight tests passed. They cover a zero-load feeder; a one-edge closed-form high-voltage solution; independent complex-power conservation including losses on all 192 cases; forced nonconvergence; deliberately corrupted voltages and incorrect slack; zero/NaN/infinite voltages; exhaustive QUBO expansion and slack projection; and catalogue/reference counts. Inspection revealed the validator originally omitted fixed-slack residuals and could divide by zero on failed voltage vectors. Both were corrected before recording this result.

## Limits and next work

No renewable-generation, held-out stress, contingency, unbalanced, meshed, topology-changing or dispatch scenarios; no cost uncertainty, physical unit calibration or sponsor dataset. No matching optimization-package cross-check, independently implemented external AC solver, heuristic comparison, QAOA simulator, quantum hardware or resource advantage. All scenarios are design scenarios, not unseen validation data. Full enumeration is reference construction, not an efficient search method. Tuning this instance's limit to expose screening error does not estimate real-world failure frequency.

This is only a reproducible foundation for the proposal's A/B/C protocol. Read the actual sponsor brief before adapting scope. Next technical milestones are an external electrical cross-check and fixed, separate design/stress instances, followed by equal-budget classical comparisons; only then is a quantum sampler comparison meaningful.
