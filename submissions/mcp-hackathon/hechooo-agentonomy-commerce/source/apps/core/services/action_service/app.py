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

from services.action_service.schemas import (
    CreateActionIntentRequest,
    RequestActionApprovalRequest,
    SubmitActionApprovalRequest,
    UpdateActionIntentRequest,
)
from services.action_service.service import ActionService
from shared.config import AppConfig
from shared.auth import require_internal_token

APP_CONFIG = AppConfig.from_env()
SERVICE = ActionService()


def create_app() -> FastAPI:
    app = FastAPI(
        title="Action Service",
        version="0.1.0",
        description="Clink Core AgentActionIntent lifecycle service.",
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
            "service": "action_service",
            "status": "ok",
            "storage": "authoritative_database",
        }

    @app.post("/actions")
    def create_action_intent(request: CreateActionIntentRequest) -> dict:
        return SERVICE.create_intent(request).to_dict()

    @app.get("/actions/{action_id}")
    def get_action_intent(action_id: str) -> dict:
        intent = SERVICE.get_intent(action_id)
        if intent is None:
            raise HTTPException(status_code=404, detail="action intent not found")
        return intent.to_dict()

    @app.post("/actions/{action_id}/update")
    def update_action_intent(action_id: str, request: UpdateActionIntentRequest) -> dict:
        try:
            intent = SERVICE.update_intent(action_id, request)
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        if intent is None:
            raise HTTPException(status_code=404, detail="action intent not found")
        return intent.to_dict()

    @app.post("/actions/{action_id}/approval-requests")
    def request_action_approval(action_id: str, request: RequestActionApprovalRequest) -> dict:
        approval = SERVICE.request_approval(action_id, request)
        if approval is None:
            raise HTTPException(status_code=404, detail="action intent not found")
        return approval.to_dict()

    @app.get("/action-approvals/{approval_id}")
    def get_action_approval(approval_id: str) -> dict:
        approval = SERVICE.get_approval(approval_id)
        if approval is None:
            raise HTTPException(status_code=404, detail="action approval not found")
        return approval.to_dict()

    @app.post("/action-approvals/{approval_id}/submit")
    def submit_action_approval(approval_id: str, request: SubmitActionApprovalRequest) -> dict:
        try:
            approval = SERVICE.submit_approval(approval_id, request)
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        if approval is None:
            raise HTTPException(status_code=404, detail="action approval not found")
        return approval.to_dict()

    return app


app = create_app()


def main() -> None:
    parser = argparse.ArgumentParser(description="Clink action service")
    parser.add_argument("--sample", action="store_true", help="Print a sample action intent instead of starting the server")
    args = parser.parse_args()

    if args.sample:
        result = SERVICE.create_intent(
            CreateActionIntentRequest(
                user_id="demo-user",
                agent_id="agent_001",
                action_type="service_purchase",
                amount_usdc="0.00001",
                target="0x2222222222222222222222222222222222222222",
                description="Demo action intent",
            )
        )
        print(json.dumps(result.to_dict(), ensure_ascii=False, indent=2))
        return

    uvicorn.run(
        app,
        host=APP_CONFIG.action_service_host,
        port=APP_CONFIG.action_service_port,
    )


if __name__ == "__main__":
    main()
