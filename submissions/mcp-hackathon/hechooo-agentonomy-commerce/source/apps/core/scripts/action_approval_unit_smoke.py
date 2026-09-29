import json
import os
import sys
import tempfile
from pathlib import Path

ROOT_DIR = Path(__file__).resolve().parents[1]
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

from services.action_service.schemas import (  # noqa: E402
    CreateActionIntentRequest,
    RequestActionApprovalRequest,
    SubmitActionApprovalRequest,
)
from services.action_service.service import ActionService  # noqa: E402
from shared.config import AppConfig  # noqa: E402


def main() -> None:
    with tempfile.TemporaryDirectory() as tmpdir:
        os.environ["ACTION_INTENT_FILE"] = str(Path(tmpdir) / "action_intents.jsonl")
        os.environ["ACTION_APPROVAL_FILE"] = str(Path(tmpdir) / "action_approvals.jsonl")

        service = ActionService(
            config=AppConfig(
                funding_database_url=f"sqlite+pysqlite:///{Path(tmpdir) / 'core.sqlite3'}"
            )
        )
        action = service.create_intent(
            CreateActionIntentRequest(
                user_id="approval-smoke-user",
                agent_id="hermes",
                action_type="market_trade",
                amount_usdc="1",
                target="polymarket:691547",
                description="Hermes wants to submit a live prediction-market order.",
            )
        )

        approval = service.request_approval(
            action.action_id,
            RequestActionApprovalRequest(
                approval_type="live_trade_confirmation",
                requested_by="hermes",
                message="Approve Hermes to submit this 1 USDC live order.",
                expires_in_minutes=10,
                metadata={"preview_id": "preview_demo"},
            ),
        )
        assert approval is not None
        assert approval.action_id == action.action_id
        assert approval.state == "requested"
        assert approval.user_id == action.user_id
        assert approval.agent_id == action.agent_id

        waiting_action = service.get_intent(action.action_id)
        assert waiting_action is not None
        assert waiting_action.state == "approval_requested"
        assert waiting_action.approval_id == approval.approval_id
        assert waiting_action.approval_state == "requested"

        submitted = service.submit_approval(
            approval.approval_id,
            SubmitActionApprovalRequest(
                decision="approved",
                approved_by="approval-smoke-user",
                wallet_address="0x20b7f4884ebd1992ee7a6257d33c1bc2e5a70f0b",
                signature="0xsigned-demo",
                note="Approved from signing console smoke.",
            ),
        )
        assert submitted is not None
        assert submitted.state == "approved"
        assert submitted.responded_at is not None

        final_action = service.get_intent(action.action_id)
        assert final_action is not None
        assert final_action.state == "user_approved"
        assert final_action.approval_state == "approved"
        assert final_action.metadata["last_approval_decision"] == "approved"
        assert any(event["event"] == "approval_submitted" for event in final_action.event_log)

        fetched = service.get_approval(approval.approval_id)
        assert fetched is not None
        assert fetched.proof_hash is not None
        assert fetched.proof_hash != "0xsigned-demo"

        print(
            json.dumps(
                {
                    "status": "ok",
                    "action_id": action.action_id,
                    "approval_id": approval.approval_id,
                    "final_state": final_action.state,
                },
                indent=2,
            )
        )


if __name__ == "__main__":
    main()
