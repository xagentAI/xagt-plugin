# -*- coding: utf-8 -*-
from ..titan_edge_mcp import TitanEdgeMCPServer

def test_diagnose_edge_health():
    server = TitanEdgeMCPServer()
    res = server.diagnose_edge_health()
    assert res["status"] == "healthy"
    assert res["metrics"]["safe_state_ready"] is True

def test_execute_safe_fallback():
    server = TitanEdgeMCPServer()
    res = server.execute_safe_fallback()
    assert res["status"] == "transition_complete"
    assert res["new_state"] == "SAFE_STANDBY"
    assert res["fail_safe_engaged"] is True
