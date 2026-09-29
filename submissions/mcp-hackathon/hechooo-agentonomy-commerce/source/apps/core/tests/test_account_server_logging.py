"""One-time account links must not appear in the server's access log."""
from types import SimpleNamespace

from services.account_service import app as account_app


def test_account_server_disables_raw_access_logs(monkeypatch):
    config = SimpleNamespace(
        account_public_base_url="https://core.example.test",
        account_service_host="127.0.0.1",
        account_service_port=8019,
    )
    application = object()
    captured = {}
    monkeypatch.setattr(account_app.AppConfig, "from_env", lambda: config)
    monkeypatch.setattr(account_app, "create_app", lambda: application)
    monkeypatch.setattr(account_app.uvicorn, "run", lambda app, **kwargs: captured.update(app=app, **kwargs))

    account_app.main()

    assert captured["app"] is application
    assert captured["host"] == "127.0.0.1"
    assert captured["port"] == 8019
    assert captured.get("access_log") is False
