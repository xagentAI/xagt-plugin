import argparse
import json
import sys
from pathlib import Path

import uvicorn
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware

ROOT_DIR = Path(__file__).resolve().parents[2]
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

from services.policy_service.schemas import EvaluateActionPolicyRequest
from services.policy_service.service import PolicyService
from shared.config import AppConfig
from shared.auth import require_internal_token

APP_CONFIG = AppConfig.from_env()
SERVICE = PolicyService()


def create_app() -> FastAPI:
    app = FastAPI(
        title="Policy Service",
        version="0.1.0",
        description="Clink Core policy gate for agentic commerce actions.",
    )

    app.add_middleware(
        CORSMiddleware,
        allow_origins=[],
        allow_credentials=False,
        allow_methods=["*"],
        allow_headers=["*"],
    )
    app.middleware("http")(require_internal_token(APP_CONFIG))

    @app.get("/healthz")
    def healthz() -> dict:
        return {
            "service": "policy_service",
            "status": "ok",
            "risk_provider": {
                "provider": APP_CONFIG.risk_provider,
                "mode": APP_CONFIG.risk_mode,
                "configured": bool(APP_CONFIG.misttrack_api_key),
            },
        }

    @app.post("/policies/evaluate")
    def evaluate_action_policy(request: EvaluateActionPolicyRequest) -> dict:
        return SERVICE.evaluate(request).to_dict()

    @app.get("/risk/readiness")
    def risk_readiness() -> dict:
        return SERVICE.get_risk_readiness()

    @app.get("/policies/{policy_decision_id}")
    def get_policy_decision(policy_decision_id: str) -> dict:
        decision = SERVICE.get_decision(policy_decision_id)
        if decision is None:
            raise HTTPException(status_code=404, detail="policy decision not found")
        return decision.to_dict()

    return app


app = create_app()


def main() -> None:
    parser = argparse.ArgumentParser(description="Clink policy service")
    parser.add_argument("--sample", action="store_true", help="Print a sample policy decision instead of starting the server")
    args = parser.parse_args()

    if args.sample:
        result = SERVICE.evaluate(
            EvaluateActionPolicyRequest(
                user_id="demo-user",
                agent_id="agent_001",
                action_type="service_purchase",
                amount_usdc="0.00001",
                risk_level="low",
                risk_score=12,
                risk_action="approve",
                user_confirmed=True,
            )
        )
        print(json.dumps(result.to_dict(), ensure_ascii=False, indent=2))
        return

    uvicorn.run(
        app,
        host=APP_CONFIG.policy_service_host,
        port=APP_CONFIG.policy_service_port,
    )


if __name__ == "__main__":
    main()
