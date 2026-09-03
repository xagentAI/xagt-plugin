"""Deterministic ExhaustiveGate tests: spec cases A-F + endpoints."""
from fastapi.testclient import TestClient

from app.main import app
from app.services.certificates import evidence_digest, issue_certificate
from app.services.claim_parser import parse_claim
from app.services.scope import scope_hash
from app.services.verifier import verify

client = TestClient(app)

BASE = {"id": "s", "resource_type": "invoice", "source": "demo-crm",
        "scope_hash": scope_hash({"status": "unpaid"}), "pagination_type": "cursor",
        "snapshot_strategy": "STRICT"}


def sess(obs, fails=None, strategy="STRICT"):
    d = dict(BASE)
    d["observations"] = obs
    d["failures"] = fails or []
    d["snapshot_strategy"] = strategy
    return d


def ob(pg, cin, cout, more, n, scope=None, snap="snap_A", items=None):
    return {"page_number": pg, "cursor_in": cin, "cursor_out": cout, "has_more": more,
            "records_seen": n, "items": items or [],
            "scope_hash": scope_hash(scope or {"status": "unpaid"}), "snapshot_id": snap}


# Case A: has_more=true + EXACT_COUNT -> UNPROVEN/PAGINATION_NOT_EXHAUSTED
def test_case_a_partial_count_unproven():
    s = sess([ob(1, None, "c2", True, 100)])
    r = verify(s, {"type": "EXACT_COUNT", "value": 100})
    assert r["verdict"] == "UNPROVEN"
    assert "PAGINATION_NOT_EXHAUSTED" in [b["code"] for b in r["blocking_reasons"]]
    assert "FETCH_NEXT_PAGE" in r["required_next_actions"]


# Case B: exhausted + match -> PROVEN + certificate
def test_case_b_full_count_proven():
    s = sess([ob(1, None, "c2", True, 100), ob(2, "c2", "c3", True, 100),
              ob(3, "c3", "c4", True, 100), ob(4, "c4", None, False, 47)])
    r = verify(s, {"type": "EXACT_COUNT", "value": 347})
    assert r["verdict"] == "PROVEN", r
    assert r["certified_value"] == 347
    assert r["records_examined"] == 347 and r["pages_examined"] == 4
    cert = issue_certificate(s, {"type": "EXACT_COUNT", "value": 347}, r)
    assert cert["verdict"] == "PROVEN" and len(cert["evidence_hash"]) == 64


# Case C: page 3 timeout -> UNPROVEN
def test_case_c_failure_unproven():
    s = sess([ob(1, None, "c2", True, 100), ob(2, "c2", None, False, 50)],
             [{"page_number": 3, "kind": "timeout"}])
    r = verify(s, {"type": "NONE"})
    assert r["verdict"] == "UNPROVEN"
    assert "UNRESOLVED_FAILURE" in [b["code"] for b in r["blocking_reasons"]]


# Case D: scope change -> UNPROVEN/SCOPE_MISMATCH
def test_case_d_scope_mismatch():
    s = sess([ob(1, None, "c2", True, 100),
              ob(2, "c2", None, False, 50, scope={"status": "all"})])
    r = verify(s, {"type": "ALL"})
    assert r["verdict"] == "UNPROVEN"
    assert "SCOPE_MISMATCH" in [b["code"] for b in r["blocking_reasons"]]


# Case E: snapshot change strict -> UNPROVEN
def test_case_e_snapshot_change():
    s = sess([ob(1, None, "c2", True, 100, snap="A"), ob(2, "c2", None, False, 50, snap="B")])
    r = verify(s, {"type": "EXACT_COUNT", "value": 150})
    assert r["verdict"] == "UNPROVEN"
    assert "SNAPSHOT_CHANGED" in [b["code"] for b in r["blocking_reasons"]]
    r2 = verify(sess([ob(1, None, "c2", True, 100, snap="A"), ob(2, "c2", None, False, 50, snap="B")], strategy="BEST_EFFORT"),
                {"type": "ALL"})
    assert r2["verdict"] == "CONDITIONAL"


# Case F: MIN proven over full domain
def test_case_f_min_proven():
    items1 = [{"id": f"p{i}", "price": 10 + i} for i in range(20)]
    items2 = [{"id": "pCheap", "price": 5}] + [{"id": f"q{i}", "price": 30 + i} for i in range(10)]
    s = sess([ob(1, None, "c2", True, 20, items=items1), ob(2, "c2", None, False, 11, items=items2)])
    r = verify(s, {"type": "MIN", "field": "price", "candidate_id": "pCheap"})
    assert r["verdict"] == "PROVEN", r
    r2 = verify(s, {"type": "MIN", "field": "price", "candidate_id": "p0"})
    assert r2["verdict"] == "UNPROVEN"
    assert "CLAIM_VALUE_MISMATCH" in [b["code"] for b in r2["blocking_reasons"]]


def test_min_partial_domain_unproven():
    s = sess([ob(1, None, "c2", True, 20)])
    r = verify(s, {"type": "MIN", "field": "price", "candidate_id": "p1"})
    assert r["verdict"] == "UNPROVEN"
    codes = [b["code"] for b in r["blocking_reasons"]]
    assert "PAGINATION_NOT_EXHAUSTED" in codes


def test_none_proven_when_empty():
    s = sess([ob(1, None, None, False, 0)])
    r = verify(s, {"type": "NONE"})
    assert r["verdict"] == "PROVEN" and r["certified_value"] == 0


def test_cursor_loop_detected():
    s = sess([ob(1, None, "c2", True, 10), ob(2, "c2", "c2", False, 10)])
    r = verify(s, {"type": "ALL"})
    assert "CURSOR_LOOP" in [b["code"] for b in r["blocking_reasons"]]


def test_cursor_chain_broken():
    s = sess([ob(1, None, "c2", True, 10), ob(2, "WRONG", None, False, 10)])
    r = verify(s, {"type": "ALL"})
    assert "CURSOR_CHAIN_BROKEN" in [b["code"] for b in r["blocking_reasons"]]


def test_scope_hash_deterministic():
    assert scope_hash({"b": 1, "a": 2}) == scope_hash({"a": 2, "b": 1})
    assert len(scope_hash({})) == 64


def test_evidence_digest_deterministic():
    s = sess([ob(1, None, None, False, 5)])
    assert evidence_digest(s) == evidence_digest(s)


def test_parser():
    assert parse_claim("There are no overdue invoices.")["type"] == "NONE"
    assert parse_claim("These are all active customers.")["type"] == "ALL"
    assert parse_claim("There are exactly 12 customers.")["type"] == "EXACT_COUNT"
    assert parse_claim("This is the cheapest flight.")["type"] == "MIN"
    assert parse_claim("This is the highest-value order.")["type"] == "MAX"


def test_health_and_verification():
    h = client.get("/health").json()
    assert h["status"] == "ok" and "commit" in h
    v = client.get("/.well-known/xagent-verification.json").json()
    assert v["schemaVersion"] == 1 and v["commit"] == h["commit"]


def test_api_full_flow():
    sid = client.post("/v1/sessions", json={"resource_type": "invoice", "source": "demo-crm",
                                            "scope": {"status": "unpaid"}}).json()["session_id"]
    r1 = client.post(f"/v1/sessions/{sid}/observe",
                     json={"page_number": 1, "cursor_out": "c2", "has_more": True, "records_seen": 100}).json()
    assert r1["coverage_status"] == "INCOMPLETE" and r1["next_expected_cursor"] == "c2"
    v1 = client.post(f"/v1/sessions/{sid}/verify", json={"claim": {"type": "EXACT_COUNT", "value": 100}}).json()
    assert v1["verdict"] == "UNPROVEN"
    client.post(f"/v1/sessions/{sid}/observe",
                json={"page_number": 2, "cursor_in": "c2", "has_more": False, "records_seen": 47}).json()
    v2 = client.post(f"/v1/sessions/{sid}/verify", json={"claim": {"type": "EXACT_COUNT", "value": 147}}).json()
    assert v2["verdict"] == "PROVEN" and v2["certificate"]["certificate_id"].startswith("proof_")
    cert = client.get(f"/v1/sessions/{sid}/certificate").json()
    assert cert["records_examined"] == 147
    assert client.post("/v1/claims/parse", json={"text": "There are no overdue tickets."}).json()["type"] == "NONE"
