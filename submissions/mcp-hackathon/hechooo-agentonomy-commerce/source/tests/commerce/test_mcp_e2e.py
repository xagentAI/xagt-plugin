"""Black-box acceptance through the actual stdio Node MCP transport."""
import json
from pathlib import Path
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[2]


def test_agent_gets_a_result_and_replay_does_not_spend_again():
    result = subprocess.run([sys.executable, '-m', 'examples.commerce.demo'],
                            cwd=ROOT, capture_output=True, text=True, timeout=90)
    assert result.returncode == 0, result.stderr + result.stdout
    report = json.loads(result.stdout)
    assert report['mode'] == 'local-simulation'
    assert report['checks']['received_result'] is True
    assert report['checks']['replay_did_not_charge'] is True
    assert report['checks']['result_retrievable'] is True
    assert report['checks']['budget_accounted'] is True

    assert report['service_result'] == {
        'count': 3, 'total': '22.25',
        'by_category': {'books': '15.00', 'food': '7.25'},
    }
    assert report['preview']['payment']['amount_atomic'] == '300000'
    assert report['checks']['identity_override_rejected'] is True
    forbidden = {'user_id', 'agent_id', 'wallet_identity_id', 'spending_grant_id',
                 'spending_authorization_id', 'authorization_resolution',
                 'receipt_signing_key', 'private_key', 'policy_decision_id', 'action_id'}
    def inspect(value):
        if isinstance(value, dict):
            assert not forbidden.intersection(value)
            for item in value.values(): inspect(item)
        elif isinstance(value, list):
            for item in value: inspect(item)
    inspect(report)
