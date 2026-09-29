# Acceptance criteria

This document defines expected behavior for calculations, data, interaction, and reproduction. Calculation expectations use independent arithmetic or mathematical properties. Recorded checks and commands are in [validation](VALIDATION.md); release conditions are in the [release guide](RELEASE.md).

| ID | Scenario | Expected behavior |
| --- | --- | --- |
| AC01 | B exactly duplicates A | The AB path equals A |
| AC02 | B is constant cash | AB equals the cash control |
| AC03 | Drawdown improves but return sacrifice exceeds its threshold | Criteria are not met; the failing condition is identified |
| AC04 | Low correlation with continuing losses | The four criteria still determine the outcome; correlation does not trigger a pass |
| AC05 | The unrounded value fails a threshold but appears equal after display rounding | Calculation precision determines the outcome; display rounding cannot change it |
| AC06 | Missing dates, duplicate or out-of-order timestamps, or non-finite values | Reject the input and identify the field or date |
| AC07 | Bar labels and valuation clocks differ | Pair only after conversion supported by explicit source evidence |
| AC08 | External cash flows, costs, or initial valuation are unknown | Block calculation and identify the required metadata |
| AC09 | Imported sampled chart points | Report insufficient data without producing complete daily statistics |
| AC10 | No criteria or only some criteria supplied | Report facts in the former case; require a complete set or a mode change in the latter |
| AC11 | Reproduction with the same inputs, method, and rules | API, workbench, and CLI metrics and outcomes agree |
| AC12 | Configuration changes or source updates | Create a new experiment or snapshot and preserve the old result |
| AC13 | Repeated tuning over the same interval | Preserve exploration labels and derivation records |
| AC14 | Validation, persistence, or response failure | Validation and failed storage transactions save no experiment. A lost response can follow a successful save: retain the prior displayed result, report uncertainty, and direct the user to history before retrying |
| AC15 | Modified evidence package or reproduction without credentials | Valid packages reproduce offline; mismatched content or results fail explicitly |
| AC16 | First-time user completes the task | The user can explain A, AB, and the cash control, identify failing conditions, and locate the evidence |
| AC17 | Public deployment | Success, insufficient-data, and error paths follow the contract; API, health, and proof agree on version binding |
| AC18 | First import in a fresh environment | A/B snapshot IDs enable validation and experiment creation; invalid imports create no usable snapshot |

## Examples and coverage

- **Recorded simulated backtests:** 60 days of equity from a pinned local AIMM version, used to verify source adaptation, workflow, and calculation.
- **Constructed ground truth:** a duplicate of A, constant cash, and a return/drawdown tradeoff with explicit mathematical expectations.
- **Insufficient data:** missing valuations, unknown costs, or incomplete curves, used to verify field-specific messages and blocked calculations.

All teaching intervals have already been observed. AIMM initial valuation, configuration, time semantics, and hashes are described in [sample provenance](../fixtures/README.md). The upstream market-price fixture is not independently certified market data.

## End-to-end workflow

1. Select or import A and B, obtaining immutable snapshot IDs.
2. Check pairing conditions and confirm the interval and rules.
3. Create the experiment and inspect all three scenarios and individual outcomes.
4. Change conditions and create a derived experiment; confirm that the original remains recoverable.
5. Download the original package and reproduce it in an environment with networking disabled.

A verification record should include the command, input hashes, version, and actual output. It should cover valid input, insufficient data, and technical failure.

## User acceptance

AC16 is performed by a user who did not implement the product. Give that user a new candidate dataset and observe whether they can independently run an experiment, explain changes relative to the baseline and cash control, locate failing conditions, and download evidence. Record completion, elapsed time, and misunderstandings to guide improvements to the interface and documentation.

Engineering checks, user acceptance, and public deployment have separate results. Actual run records are in [validation](VALIDATION.md); public version and service checks are in the [release guide](RELEASE.md).
