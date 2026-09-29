"""A lost/mismatched worker reply must never be reused as a later purchase reply."""
import json
import subprocess
import sys

import pytest
from examples.commerce import node


def child_factory(monkeypatch, code):
    original = subprocess.Popen
    def spawn(_args, **kwargs):
        return original([sys.executable, '-u', '-c', code], **kwargs)
    monkeypatch.setattr(node.subprocess, 'Popen', spawn)


class NoReply:
    def __enter__(self): return self
    def __exit__(self, *args): pass
    def register(self, *args): pass
    def select(self, **kwargs): return []


def test_timeout_closes_the_channel_before_another_request(tmp_path, monkeypatch):
    child_factory(monkeypatch, 'import sys,time; sys.stdin.readline(); time.sleep(30)')
    monkeypatch.setattr(node.selectors, 'DefaultSelector', NoReply)
    bridge = node.MarketplaceBridge(tmp_path)
    process = bridge.process
    try:
        with pytest.raises(TimeoutError):
            bridge.request('snapshot')
        assert process.poll() is not None
        with pytest.raises(RuntimeError, match='broken|exited'):
            bridge.request('snapshot')
    finally:
        bridge.close()


def test_wrong_response_id_breaks_channel(tmp_path, monkeypatch):
    code = ('import sys,json; sys.stdin.readline(); '
            'print(json.dumps({"id":-1,"result":{"state":"delivered"}}),flush=True); '
            'sys.stdin.read()')
    child_factory(monkeypatch, code)
    bridge = node.MarketplaceBridge(tmp_path)
    try:
        with pytest.raises(RuntimeError, match='mismatched'):
            bridge.request('execute', {'preview_id': 'preview_1'})
    finally:
        bridge.close()
