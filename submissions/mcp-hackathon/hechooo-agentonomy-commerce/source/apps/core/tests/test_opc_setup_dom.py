from __future__ import annotations

from services.account_service.console import ACCOUNT_CONSOLE_CSS, ACCOUNT_CONSOLE_HTML


def test_opc_setup_has_one_primary_action_and_scoped_legacy_hiding() -> None:
    """The OPC bootstrap view owns one primary action and hides old panels only there."""

    assert 'id="opc-setup"' in ACCOUNT_CONSOLE_HTML
    assert 'id="opc-setup-submit"' in ACCOUNT_CONSOLE_HTML
    assert ACCOUNT_CONSOLE_HTML.count('id="opc-setup-submit"') == 1
    assert 'body[data-account-view="authorization"][data-opc-setup]' in ACCOUNT_CONSOLE_CSS
    assert '#opc-setup-submit' in ACCOUNT_CONSOLE_CSS


def test_opc_setup_keeps_provider_and_address_selection_visible() -> None:
    assert 'id="wallet-provider-options"' in ACCOUNT_CONSOLE_HTML
    assert 'id="wallet-account-options"' in ACCOUNT_CONSOLE_HTML
    assert 'body[data-account-view="authorization"][data-opc-setup] #connect-wallet' in ACCOUNT_CONSOLE_CSS
