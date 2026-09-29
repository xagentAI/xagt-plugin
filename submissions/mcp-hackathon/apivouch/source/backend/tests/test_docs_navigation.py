from fastapi.testclient import TestClient

from app.main import app

client = TestClient(app)


def test_docs_offer_explicit_route_back_to_product_home():
    response = client.get("/docs")

    assert response.status_code == 200
    assert 'class="apivouch-docs-nav"' in response.text
    assert 'href="/"' in response.text
    assert "Back to APIVouch" in response.text
    assert response.headers["cache-control"] == "no-cache, max-age=0, must-revalidate"


def test_product_docs_links_preserve_browser_history():
    response = client.get("/")

    assert response.status_code == 200
    assert response.text.count('href="/docs"') == 2
    assert 'href="/docs" target="_blank"' not in response.text
