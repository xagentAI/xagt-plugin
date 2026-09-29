import json
import os
import sys
import tempfile
from pathlib import Path

ROOT_DIR = Path(__file__).resolve().parents[1]
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

from services.policy_service.schemas import EvaluateActionPolicyRequest  # noqa: E402
from services.policy_service.service import PolicyService  # noqa: E402


def _evaluate(service: PolicyService, **overrides) -> dict:
    payload = {
        "user_id": "prediction-policy-user",
        "agent_id": "hermes_agent",
        "amount_usdc": "1",
        "risk_level": "low",
        "risk_score": 20,
        "risk_action": "approve",
        "requires_confirmation": True,
        "live_mode": True,
        "metadata": {"platform": "polymarket", "market_id": "558934"},
    }
    payload.update(overrides)
    return service.evaluate(EvaluateActionPolicyRequest(**payload)).to_dict()


def main() -> None:
    with tempfile.TemporaryDirectory() as tmpdir:
        os.environ["POLICY_DECISION_FILE"] = str(Path(tmpdir) / "policy_decisions.jsonl")
        service = PolicyService()

        preview = _evaluate(service, action_type="prediction_market_order_preview")
        assert preview["decision"] == "needs_confirmation"
        assert preview["reason_code"] == "USER_CONFIRMATION_REQUIRED"
        assert preview["required_action"] == "request_user_confirmation"
        assert "UNSUPPORTED_ACTION_TYPE" != preview["reason_code"]

        execute_without_confirmation = _evaluate(
            service,
            action_type="prediction_market_order_execute",
            user_confirmed=False,
            metadata={"preview_id": "pm_preview_test", "execution_ready": True},
        )
        assert execute_without_confirmation["decision"] == "needs_confirmation"
        assert execute_without_confirmation["reason_code"] == "USER_CONFIRMATION_REQUIRED"
        assert execute_without_confirmation["required_action"] == "request_user_confirmation"

        execute_confirmed = _evaluate(
            service,
            action_type="prediction_market_order_execute",
            user_confirmed=True,
            metadata={"preview_id": "pm_preview_test", "execution_ready": True},
        )
        assert execute_confirmed["approved"] is True
        assert execute_confirmed["decision"] == "approved"
        assert execute_confirmed["reason_code"] == "APPROVED"

        execute_not_ready = _evaluate(
            service,
            action_type="prediction_market_order_execute",
            user_confirmed=True,
            metadata={"preview_id": "pm_preview_test", "execution_ready": False},
        )
        assert execute_not_ready["decision"] == "blocked"
        assert execute_not_ready["reason_code"] == "EXECUTION_NOT_READY"
        assert execute_not_ready["required_action"] == "check_execution_readiness"

        unsupported = _evaluate(service, action_type="unknown_prediction_action", user_confirmed=True)
        assert unsupported["decision"] == "blocked"
        assert unsupported["reason_code"] == "UNSUPPORTED_ACTION_TYPE"

        print(
            json.dumps(
                {
                    "status": "ok",
                    "preview_decision": preview["decision"],
                    "execute_decision": execute_confirmed["decision"],
                    "not_ready_reason": execute_not_ready["reason_code"],
                },
                indent=2,
            )
        )


if __name__ == "__main__":
    main()
