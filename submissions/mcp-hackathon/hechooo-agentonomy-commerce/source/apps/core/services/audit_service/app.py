import argparse
import json
import sys
from pathlib import Path

import uvicorn
from fastapi import FastAPI, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware

ROOT_DIR = Path(__file__).resolve().parents[2]
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

from services.audit_service.schemas import WriteAuditEventRequest
from services.audit_service.service import AuditService
from shared.config import AppConfig
from shared.auth import require_internal_token

APP_CONFIG = AppConfig.from_env()
SERVICE = AuditService()


def create_app(
    *,
    service: AuditService | None = None,
    config: AppConfig | None = None,
) -> FastAPI:
    audit_service = service or SERVICE
    app_config = config or APP_CONFIG
    app = FastAPI(
        title="Audit Service",
        version="0.1.0",
        description="Clink Core append-only audit trail service.",
    )

    app.add_middleware(
        CORSMiddleware,
        allow_origins=[],
        allow_credentials=False,
        allow_methods=["*"],
        allow_headers=["*"],
    )
    app.middleware("http")(require_internal_token(app_config))

    @app.get("/healthz")
    def healthz() -> dict:
        return {
            "service": "audit_service",
            "status": "ok",
            "storage": str(audit_service.storage_file),
        }

    @app.post("/audit/events")
    def write_audit_event(request: WriteAuditEventRequest) -> dict:
        try:
            return audit_service.write_event(request).to_dict()
        except ValueError as exc:
            if str(exc) == "audit idempotency key conflicts":
                raise HTTPException(status_code=409, detail=str(exc)) from exc
            raise

    @app.get("/audit/events/{event_id}")
    def get_audit_event(event_id: str) -> dict:
        event = audit_service.get_event(event_id)
        if event is None:
            raise HTTPException(status_code=404, detail="audit event not found")
        return event.to_dict()

    @app.get("/audit/trail")
    def get_audit_trail(
        action_id: str | None = Query(default=None),
        user_id: str | None = Query(default=None),
        agent_id: str | None = Query(default=None),
    ) -> dict:
        return audit_service.get_trail(
            action_id=action_id, user_id=user_id, agent_id=agent_id
        ).to_dict()

    @app.get("/audit/summary")
    def get_audit_summary(
        user_id: str = Query(min_length=1, max_length=96),
        limit: int = Query(default=8, ge=1, le=50),
    ) -> list[dict]:
        return [
            event.to_dict()
            for event in audit_service.get_user_summary(user_id, limit=limit)
        ]

    return app


app = create_app()


def main() -> None:
    parser = argparse.ArgumentParser(description="Clink audit service")
    parser.add_argument("--sample", action="store_true", help="Print a sample audit event instead of starting the server")
    args = parser.parse_args()

    if args.sample:
        result = SERVICE.write_event(
            WriteAuditEventRequest(
                event_type="action_intent_created",
                source_service="audit_service_sample",
                action_id="act_demo",
                user_id="demo-user",
                agent_id="agent_001",
                payload={"message": "sample audit event"},
            )
        )
        print(json.dumps(result.to_dict(), ensure_ascii=False, indent=2))
        return

    uvicorn.run(
        app,
        host=APP_CONFIG.audit_service_host,
        port=APP_CONFIG.audit_service_port,
    )


if __name__ == "__main__":
    main()
