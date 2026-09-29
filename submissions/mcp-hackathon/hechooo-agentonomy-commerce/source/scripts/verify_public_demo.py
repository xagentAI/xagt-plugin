#!/usr/bin/env python3
"""Verify the public visitor flow with simulated funds; never print cookies.

A private state file permits replay after restart without a new charge. Keep it
outside the source tree and submission. Output JSON contains only safe evidence.
"""
import argparse
import http.cookiejar
import json
import os
from pathlib import Path
import tempfile
import urllib.error
import urllib.request
from urllib.parse import urlsplit

CSV = ('transaction_id,date,description,amount,currency,category\n'
       't1,2026-09-01,Hosting,-12.50,USD,software\n'
       't2,2026-09-02,Invoice,40.00,USD,revenue\n'
       't1,2026-09-01,Hosting,-12.50,USD,software\n')


def write_private(path, value):
    path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    fd, temporary = tempfile.mkstemp(dir=path.parent)
    try:
        os.fchmod(fd, 0o600)
        with os.fdopen(fd, 'w') as stream:
            json.dump(value, stream)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, path)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)


class Visitor:
    def __init__(self, base_url, credential=None):
        self.base_url = base_url.rstrip('/')
        self.jar = http.cookiejar.CookieJar()
        self.opener = urllib.request.build_opener(urllib.request.HTTPCookieProcessor(self.jar))
        self.credential = credential

    def request(self, path, body=None, expected=200, origin=True, key=None):
        headers = {}
        if self.credential:
            headers['Cookie'] = 'agentonomy_demo=' + self.credential
        if body is not None:
            headers['Content-Type'] = 'application/json'
            if origin:
                headers['Origin'] = self.base_url
        if key:
            headers['Idempotency-Key'] = key
        request = urllib.request.Request(self.base_url + path,
                                         data=json.dumps(body).encode() if body is not None else None,
                                         headers=headers)
        try:
            response = self.opener.open(request, timeout=65)
        except urllib.error.HTTPError as error:
            response = error
        with response:
            if response.status != expected:
                raise RuntimeError(f'Unexpected HTTP status for {path}: {response.status}, expected {expected}')
            value = json.load(response)
        for cookie in self.jar:
            if cookie.name == 'agentonomy_demo':
                self.credential = cookie.value
        return value


def verify(base_url, commit, state_file, resume=False):
    parsed = urlsplit(base_url)
    assert parsed.scheme == 'https' or (parsed.scheme == 'http' and parsed.hostname in ('localhost', '127.0.0.1'))
    assert not parsed.username and not parsed.password and parsed.path in ('', '/') and not parsed.query and not parsed.fragment
    anonymous = Visitor(base_url)
    health = anonymous.request('/health')
    assert health['commit'] == commit and health['status'] == 'ok' and health['real_funds'] is False
    assert anonymous.request('/.well-known/xagent-verification.json')['commit'] == commit
    anonymous.request('/v1/budget', expected=401)
    anonymous.request('/demo/v1/budget', expected=401)
    anonymous.request('/demo/session', {}, expected=403, origin=False)
    if resume:
        assert state_file.is_file() and state_file.stat().st_mode & 0o077 == 0
        saved = json.loads(state_file.read_text())
        alice = Visitor(base_url, saved['credential'])
        session = alice.request('/demo/session')
        assert session['session_id'] == saved['session_id'] and session['authenticated']
        pending = saved.get('preview')
        if pending is None:
            pending = alice.request('/demo/v1/previews', {'offering_id': 'csv-reconciliation-v1', 'csv_text': CSV}, key='public-acceptance')
            saved['preview'] = pending
            write_private(state_file, saved)
        bought = saved.get('purchase')
        if bought is None:
            bought = alice.request('/demo/v1/purchases', {'preview_id': pending['preview_id']})
            saved['purchase'] = bought
            write_private(state_file, saved)
    else:
        if state_file.exists():
            raise RuntimeError('State file exists; use --resume to avoid a new charge')
        alice = Visitor(base_url)
        session = alice.request('/demo/session', {})
        # Persist ownership before any charge, so interrupted verification never loses it.
        saved = {'credential': alice.credential, 'session_id': session['session_id']}
        write_private(state_file, saved)
        pending = alice.request('/demo/v1/previews', {'offering_id': 'csv-reconciliation-v1', 'csv_text': CSV}, key='public-acceptance')
        saved['preview'] = pending
        write_private(state_file, saved)
        bought = alice.request('/demo/v1/purchases', {'preview_id': pending['preview_id']})
        saved['purchase'] = bought
        write_private(state_file, saved)
    assert bought['state'] == 'delivered' and bought['real_funds'] is False
    result = bought['service_result']
    assert result['unique_transaction_count'] == 2 and result['duplicate_ids'] == ['t1'] and result['net_totals'] == {'USD': '27.50'}
    assert alice.request('/demo/session', {})['session_id'] == session['session_id']
    recovered = alice.request('/demo/v1/purchases/' + bought['purchase_id'])
    assert recovered['service_result'] == result
    replay = alice.request('/demo/v1/purchases', {'preview_id': pending['preview_id']})
    assert replay['purchase_id'] == bought['purchase_id'] and replay['service_result'] == result
    budget = alice.request('/demo/v1/budget')
    assert budget['used_amount_usdc'] == '0.30' and budget['remaining_amount_usdc'] == '0.70'
    assert budget['settlement_submissions'] == budget['merchant_deliveries'] == 1
    if not resume:
        bob = Visitor(base_url)
        assert bob.request('/demo/session', {})['session_id'] != session['session_id']
        assert bob.request('/demo/v1/budget')['remaining_amount_usdc'] == '1.00'
        bob.request('/demo/v1/purchases/' + bought['purchase_id'], expected=404)
        bob.request('/demo/v1/purchases', {'preview_id': pending['preview_id']}, expected=404)
        assert bob.request('/demo/v1/budget')['used_amount_usdc'] == '0.00'
    return {'status': 'passed', 'commit': commit, 'real_funds': False,
            'public_browser_session': True, 'manual_token_required': False,
            'session_restored': resume, 'cross_visitor_isolation_checked': not resume,
            'same_purchase_on_replay': True,
            'budget': {key: budget[key] for key in ('used_amount_usdc', 'remaining_amount_usdc', 'settlement_submissions', 'merchant_deliveries')}}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--base-url', required=True)
    parser.add_argument('--expected-commit', required=True)
    parser.add_argument('--state-file', type=Path, required=True)
    parser.add_argument('--resume', action='store_true')
    args = parser.parse_args()
    result = verify(args.base_url, args.expected_commit, args.state_file, args.resume)
    print(json.dumps(result, indent=2))


if __name__ == '__main__':
    main()
