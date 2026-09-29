"""A resolved signed grant must retain Core's interaction decision at policy."""
import pytest

from tests.test_purchase_result_and_reputation import (
    MerchantResponse, RecordingClient, RecordingCore, build_repository,
    build_purchase_service,
)

MISSING = object()


class InteractionCore(RecordingCore):
    def __init__(self, interaction):
        super().__init__()
        self.interaction = interaction
        self.policy_request = None

    def resolve_authorization(self, payload):
        result = super().resolve_authorization(payload)
        if self.interaction is not MISSING:
            result['user_interaction_required'] = self.interaction
        return result

    def evaluate_policy(self, payload):
        self.policy_request = payload
        approved = not payload.get('requires_confirmation', True) or payload['user_confirmed']
        return {'policy_decision_id': 'policy_1', 'approved': approved,
                'reason_code': 'APPROVED' if approved else 'USER_CONFIRMATION_REQUIRED'}


@pytest.mark.parametrize('interaction,expected', [
    (False, 'delivered'), (True, 'confirmation_required'),
    (MISSING, 'confirmation_required'), (None, 'confirmation_required'),
    (0, 'confirmation_required'), ('false', 'confirmation_required'),
])
def test_policy_respects_only_explicit_core_permission_for_silent_purchase(tmp_path, interaction, expected):
    repository, offering = build_repository(tmp_path)
    core = InteractionCore(interaction)
    client = RecordingClient(MerchantResponse({'answer': 'purchased result'}))
    service = build_purchase_service(repository, offering, core, client=client)
    preview = service.create_preview(user_id='hermes', offering_id=offering.offering_id,
                                     service_input={'query': 'example'})
    result = service.execute(preview.preview_id)
    assert result.state == expected
    assert core.policy_request['user_confirmed'] is False
    assert core.policy_request.get('requires_confirmation', True) is (interaction is not False)
    assert core.settlements == (1 if expected == 'delivered' else 0)
