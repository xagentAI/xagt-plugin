# Constructed teaching examples

`app/adapters/demos.py` generates examples deterministically. Independent hand-calculation inputs are in `tests/test_domain_engine.py`. Duplicate, cash, and missing-day examples apply explicit transformations to AIMM records; the return/drawdown tradeoff uses constructed curves. See [sample documentation](../README.md) for each input's source and expected behavior.
