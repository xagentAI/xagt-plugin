import pytest

from test_asset_allowances import allowance_context, verify


def test_prepared_amount_is_verified_before_recording_allowance(allowance_context):
    service, repository, _rpc, identity = allowance_context
    with pytest.raises(ValueError, match="prepared amount"):
        verify(service, identity, expected_amount_atomic=20_000_000)
    assert repository.asset_allowances(identity.wallet_identity_id) == []
    actual = verify(service, identity, expected_amount_atomic=2_000_000)
    assert actual.approved_amount_atomic == 2_000_000
