import time


def test_values_survive_restart_and_expire(tmp_path):
    from agentonomy_commerce.storage import SQLiteStore

    now = [100.0]
    path = tmp_path / "values.sqlite3"
    first = SQLiteStore(path, clock=lambda: now[0])
    first.set("input", {"csv_text": "example"}, 10)
    second = SQLiteStore(path, clock=lambda: now[0])
    assert second.get("input") == {"csv_text": "example"}
    now[0] = 110.0
    assert second.get("input") is None


def test_results_have_seven_day_retention_but_inputs_do_not(tmp_path):
    from agentonomy_commerce.storage import SQLiteStore

    now = [time.time()]
    store = SQLiteStore(tmp_path / "values.sqlite3", clock=lambda: now[0])
    store.set("purchase_result:p1", {"total": "0.30"}, 900)
    store.set("preview_1", {"csv_text": "sensitive input"}, 300)
    now[0] += 3600
    assert store.get("preview_1") is None
    assert store.get("purchase_result:p1") == {"total": "0.30"}
    now[0] += 7 * 86400
    assert store.get("purchase_result:p1") is None


def test_acquire_pop_and_delete_match_marketplace_contract(tmp_path):
    from agentonomy_commerce.storage import SQLiteStore

    now = [100.0]
    store = SQLiteStore(tmp_path / "values.sqlite3", clock=lambda: now[0])
    store.set("input", {"value": 1}, 10)
    now[0] += 5
    assert store.acquire("input", 20) == {"value": 1}
    now[0] += 10
    assert store.pop("input") == {"value": 1}
    assert store.pop("input") is None
    store.set("input", {}, 1)
    assert store.delete("input") is True
    assert store.delete("input") is False


def test_worker_selection_is_explicit_and_preserves_arguments(tmp_path, monkeypatch):
    import subprocess
    from examples.commerce import node

    original = subprocess.Popen
    calls = []

    def spawn(args, **kwargs):
        calls.append(args)
        return original([args[0], "-c", "import sys; sys.stdin.read()"], **kwargs)

    monkeypatch.setattr(node.subprocess, "Popen", spawn)
    bridge = node.MarketplaceBridge(
        tmp_path, worker_module="agentonomy_commerce.worker", worker_args=("18081",)
    )
    bridge.close()
    assert calls[0][1:] == ["-m", "agentonomy_commerce.worker", str(tmp_path), "18081"]
