from dataclasses import replace

import pytest
from fastapi.testclient import TestClient

from agentonomy_commerce.api import create_app
from agentonomy_commerce.settings import Settings
from test_review_api import Bridge, TOKEN, COMMIT
from test_review_restart import CSV, settings_for

ORIGIN = 'https://testserver'


def app_for(path, **changes):
    return create_app(Settings(path, TOKEN, COMMIT, 'hechooo-agentonomy-commerce',
                               demo_origin=ORIGIN, **changes), bridge_factory=Bridge)


def start(client):
    response = client.post('/demo/session', json={}, headers={'Origin': ORIGIN})
    assert response.status_code == 200, response.text
    return response


def test_public_session_cookie_restore_and_private_auth_separation(tmp_path):
    with TestClient(app_for(tmp_path), base_url=ORIGIN) as client:
        assert client.get('/demo/session').json() == {'enabled': True, 'authenticated': False}
        assert client.get('/demo/v1/budget').status_code == 401
        response = start(client)
        cookie = response.headers['set-cookie'].lower()
        assert all(flag in cookie for flag in ('httponly', 'secure', 'samesite=strict', 'path=/'))
        assert 'domain=' not in cookie
        assert TOKEN not in response.text
        assert client.cookies['agentonomy_demo'] not in response.text
        identity = response.json()['session_id']
        assert start(client).json()['session_id'] == identity
        assert 'set-cookie' not in start(client).headers
        assert client.get('/demo/session').json()['session_id'] == identity
        assert client.get('/demo/v1/budget').status_code == 200
        assert client.get('/v1/budget').status_code == 401
        assert client.get('/v1/budget', headers={'Authorization': f'Bearer {TOKEN}'}).status_code == 200


def test_origin_body_identity_and_cookie_guards(tmp_path):
    with TestClient(app_for(tmp_path), base_url=ORIGIN) as client:
        for origin in (None, 'https://attacker.example', 'null'):
            assert client.post('/demo/session', json={}, headers={} if origin is None else {'Origin': origin}).status_code == 403
        assert client.post('/demo/session', json={'session_id': 'chosen'}, headers={'Origin': ORIGIN}).status_code == 422
        start(client)
        assert client.post('/demo/v1/purchases', json={'preview_id': 'preview_x'}).status_code == 403
        assert client.post('/demo/v1/previews', json={'offering_id': 'csv-reconciliation-v1', 'csv_text': CSV, 'budget': 999},
                           headers={'Origin': ORIGIN, 'Idempotency-Key': 'x'}).status_code == 422
        assert client.post('/demo/v1/previews', content=b'x' * 262145, headers={'Origin': ORIGIN}).status_code == 413
        client.cookies.clear()
        assert client.get('/demo/v1/budget', headers={'Cookie': 'agentonomy_demo=forged', 'Authorization': f'Bearer {TOKEN}'}).status_code == 401


def test_demo_disabled_by_default(tmp_path):
    app = create_app(Settings(tmp_path, TOKEN, COMMIT, 'hechooo-agentonomy-commerce'), bridge_factory=Bridge)
    with TestClient(app) as client:
        assert client.get('/demo/session').json() == {'enabled': False, 'authenticated': False}
        assert client.post('/demo/session', json={}, headers={'Origin': ORIGIN}).status_code == 404
        assert client.get('/demo/v1/budget').status_code == 404


@pytest.mark.parametrize('origin', ['https://example.com/path', 'http://example.com', 'https://user:pass@example.com',
                                    'https://example.com?x=1', 'https://example.com#x', 'null', 'https://example.com:wrong'])
def test_invalid_demo_origin_rejected(tmp_path, origin):
    with pytest.raises(ValueError):
        Settings(tmp_path, TOKEN, COMMIT, 'hechooo-agentonomy-commerce', demo_origin=origin)


def test_rate_limit_is_per_visitor(tmp_path):
    with TestClient(app_for(tmp_path, requests_per_minute=1), base_url=ORIGIN) as client:
        start(client)
        assert client.get('/demo/v1/budget').status_code == 200
        assert client.get('/demo/v1/budget').status_code == 429
        client.cookies.clear()
        start(client)
        assert client.get('/demo/v1/budget').status_code == 200


def test_real_visitors_isolate_and_restore_orders_after_restart(tmp_path):
    settings = replace(settings_for(tmp_path), demo_origin=ORIGIN)
    app = create_app(settings)
    with TestClient(app, base_url=ORIGIN) as alice:
        alice_identity = start(alice).json()['session_id']
        cookie = alice.cookies['agentonomy_demo']
        pending = alice.post('/demo/v1/previews', json={'offering_id': 'csv-reconciliation-v1', 'csv_text': CSV},
                             headers={'Origin': ORIGIN, 'Idempotency-Key': 'isolated'}).json()
        bought_response = alice.post('/demo/v1/purchases', json={'preview_id': pending['preview_id']}, headers={'Origin': ORIGIN})
        assert bought_response.status_code == 200, bought_response.text
        bought = bought_response.json()
        assert bought['state'] == 'delivered'
        bob = TestClient(app, base_url=ORIGIN)
        try:
            assert start(bob).json()['session_id'] != alice_identity
            assert bob.get('/demo/v1/budget').json()['remaining_amount_usdc'] == '1.00'
            assert bob.get('/demo/v1/purchases/' + bought['purchase_id']).status_code == 404
            foreign = bob.post('/demo/v1/purchases', json={'preview_id': pending['preview_id']}, headers={'Origin': ORIGIN})
            assert foreign.status_code in (404, 422), foreign.text
            assert bob.get('/demo/v1/budget').json()['used_amount_usdc'] == '0.00'
        finally:
            bob.close()
        assert alice.get('/demo/v1/budget').json()['used_amount_usdc'] == '0.30'
        assert alice.get('/v1/budget', headers={'Authorization': f'Bearer {settings.api_token}'}).json()['used_amount_usdc'] == '0.00'
    with TestClient(create_app(settings), base_url=ORIGIN) as alice:
        alice.cookies.set('agentonomy_demo', cookie)
        assert start(alice).json()['session_id'] == alice_identity
        recovered = alice.get('/demo/v1/purchases/' + bought['purchase_id']).json()
        assert recovered['service_result'] == bought['service_result']
        replay = alice.post('/demo/v1/purchases', json={'preview_id': pending['preview_id']}, headers={'Origin': ORIGIN}).json()
        assert replay['purchase_id'] == bought['purchase_id']
        budget = alice.get('/demo/v1/budget').json()
        assert budget['used_amount_usdc'] == '0.30'
        assert budget['remaining_amount_usdc'] == '0.70'
        assert budget['settlement_submissions'] == budget['merchant_deliveries'] == 1
