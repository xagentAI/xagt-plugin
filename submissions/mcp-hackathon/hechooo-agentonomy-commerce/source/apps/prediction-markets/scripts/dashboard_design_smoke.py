import json
from pathlib import Path


ROOT_DIR = Path(__file__).resolve().parents[1]
APP_FILE = ROOT_DIR / "dashboard_frontend" / "src" / "App.jsx"
STYLE_FILE = ROOT_DIR / "dashboard_frontend" / "src" / "styles.css"


def main() -> None:
    app = APP_FILE.read_text()
    styles = STYLE_FILE.read_text()

    required_app_markers = [
        "Active Signal",
        "Clink Audit Strip",
        "Trade Blotter",
        "Holdings Table",
        "Money State",
        "Agentonomy Observations",
        "Watch the agent money loop.",
        "Refreshes every 20s",
        "idea-ledger",
        "idea-row",
        "thesis-ledger",
        "audit-strip",
        "trade-blotter",
        "blotter-row",
        "holdings-table",
        "holding-row",
        "scan-layer",
        "radar-grid",
        "Account Control",
        "Core Account",
        "Polymarket Account",
        "Open Core Account",
        "Unbind Polymarket account",
        "Revoke spending cap",
        "account-control",
        "Funding Route",
        "EOA Direct Trading",
        "x402 funding",
        "funding-route",
        "Account / Binding Console",
        "Trading Dashboard",
        "AccountWorkspace",
        "TradingWorkspace",
        "window.location.hash",
        "#account",
        "#dashboard",
    ]
    required_style_markers = [
        ".thesis-ledger",
        ".idea-ledger",
        ".idea-row",
        ".idea-row-status",
        ".idea-row-market",
        ".audit-strip",
        ".trade-blotter",
        ".blotter-row",
        ".holdings-table",
        ".holding-row",
        ".control-ledger",
        ".scan-layer",
        ".radar-grid",
        "@keyframes terminal-scan",
        "@media (prefers-reduced-motion: reduce)",
        ".account-control",
        ".account-control::before",
        ".account-card",
        ".account-actions",
        ".danger-button",
        ".funding-route",
        ".route-badge",
        ".product-nav",
        ".nav-pill",
        ".workspace-intro",
        ".account-workspace",
        ".trading-workspace",
    ]
    banned_style_markers = [
        ".aurora",
        "glassmorphism",
        "radial-gradient(circle, var(--mint)",
        "radar-beam",
        "capital-orbit",
        "market-lock",
        "gate-circuit",
        "data-beacon",
        "tape-row",
        ".idea-card",
        ".idea-board",
    ]

    missing_app = [marker for marker in required_app_markers if marker not in app]
    missing_styles = [marker for marker in required_style_markers if marker not in styles]
    banned_present = [marker for marker in banned_style_markers if marker in styles]

    assert not missing_app, f"Missing App.jsx design markers: {missing_app}"
    assert not missing_styles, f"Missing styles.css design markers: {missing_styles}"
    assert not banned_present, f"AI-dashboard visual markers still present: {banned_present}"
    assert "hermes" not in app.lower(), "Browser UI still exposes the Hermes name"

    trading_section = app.split("function TradingWorkspace", 1)[-1].split("function AccountWorkspace", 1)[0]
    assert "<AccountControl" not in trading_section, "TradingWorkspace should not render AccountControl directly"

    print(json.dumps({"status": "ok", "checked": len(required_app_markers) + len(required_style_markers)}, indent=2))


if __name__ == "__main__":
    main()
