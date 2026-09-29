from life_exchange_rate import main


def test_vercel_revision_is_platform_bound(monkeypatch):
    monkeypatch.setenv("VERCEL_GIT_COMMIT_SHA", "a" *40)
    monkeypatch.setenv("REVIEW_COMMIT", "stale-local")
    assert main.health()["commit"] == "a" *40
    assert main.xagent_verification()["commit"] == "a" *40


def test_vercel_origin_and_submission_binding(monkeypatch):
    monkeypatch.delenv("PUBLIC_BASE_URL", raising=False)
    monkeypatch.setenv("VERCEL_PROJECT_PRODUCTION_URL", "project.example")
    monkeypatch.setenv("SUBMISSION_SLUG", "kongkoukk-life-exchange-rate")
    proof = main.xagent_verification()
    assert proof["slug"] == "kongkoukk-life-exchange-rate"
    assert proof["apiBaseUrl"] == "https://project.example"
    assert proof["mcp"] == "https://project.example/mcp/"
    assert "project.example" in main._transport_security().allowed_hosts


def test_self_hosted_origin_override(monkeypatch):
    monkeypatch.setenv("VERCEL_PROJECT_PRODUCTION_URL", "project.example")
    monkeypatch.setenv("PUBLIC_BASE_URL", "https://custom.example/")
    assert main._base_url() == "https://custom.example"
