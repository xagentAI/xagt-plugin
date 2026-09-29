# Domain calculations

`engine.py` is the standard-library-only calculation implementation shared by the workbench, API, and offline reproducer. It accesses neither the network nor a database. [METHOD.md](../../docs/METHOD.md) defines the financial interpretation; [IMPLEMENTATION-CONTRACT.md](../../docs/IMPLEMENTATION-CONTRACT.md) specifies the machine interface.

- `normalize_curve` returns a normalized curve or raises `InputError` with field-specific issues.
- `validate_pair` checks two complete curves and any explicitly selected interval. Invalid pairs have `coverage=null`.
- `evaluate` returns three paths, metrics, individual research criteria, and limitations. `coverage.observations` includes the separate initial valuation; `diagnostics.return_observations` counts daily returns.
- `comparison_facts` always contains the four differences relative to A/cash in percentage points, whether or not criteria were supplied. `criteria_results` adds thresholds and outcomes only when all criteria are supplied. The interface does not need to calculate the differences again.
- Every calculation uses an independent 50-significant-digit Decimal context with `HALF_EVEN` rounding. It is unaffected by the caller's context and does not change the caller's precision. Threshold decisions use calculated values rather than display rounding, with no extra tolerance.
- Numeric input allows at most 40 significant digits, excluding insignificant trailing zeros; nonzero numbers have adjusted exponents from -30 to 30. Numeric text is limited to 160 characters. Equity must be positive. Out-of-range values are rejected rather than truncated. Output uses canonical decimal strings; auxiliary correlation is a finite float or `null`.
- With only one daily return, sample standard deviation and correlation are `null`. Correlation with zero volatility is also `null`.
- `cost_model` cannot be empty or an explicit unknown-cost marker. The complete marker list, including localized input values, is in the [input contract](../../docs/IMPLEMENTATION-CONTRACT.md). This check does not certify other cost declarations; an explicit zero-fee simulation identifier is allowed.
- New API result text is English and declares `display_language=en`. Legacy presentation is retained only to reproduce older evidence completely, without altering calculations or bypassing comparison of stored result text.

Behavior tests in `tests/test_domain_engine.py` cover independent arithmetic, identity properties, missing-data rejection, threshold boundaries, and numerical-context isolation.
