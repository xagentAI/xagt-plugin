"""The public demo tool contract keeps identity and authorization out of inputs."""
from examples.commerce.node import TOOL_SCHEMAS


def test_tools_do_not_accept_identity_or_authorization_overrides():
    expected = {'search_clink_services', 'get_clink_service_details',
                'create_clink_purchase_preview', 'execute_clink_purchase',
                'get_clink_purchase'}
    assert set(TOOL_SCHEMAS) == expected
    forbidden = {'user_id', 'agent_id', 'spending_authorization_id',
                 'transaction_hash', 'payment_response', 'receipt_signing_key'}
    for schema in TOOL_SCHEMAS.values():
        assert not forbidden.intersection(schema['properties'])
        assert schema['additionalProperties'] is False
    assert TOOL_SCHEMAS['execute_clink_purchase']['required'] == ['preview_id']


def test_order_input_rejects_undeclared_nested_identity_fields():
    import jsonschema
    import pytest
    schema = TOOL_SCHEMAS['create_clink_purchase_preview']
    valid = {'offering_id': 'offering_1', 'service_input': {
        'orders': [{'amount': '1.25', 'category': 'books'}]}}
    jsonschema.validate(valid, schema)
    with pytest.raises(jsonschema.ValidationError):
        jsonschema.validate({**valid, 'service_input': {
            **valid['service_input'], 'user_id': 'another-user'}}, schema)
    with pytest.raises(jsonschema.ValidationError):
        jsonschema.validate({**valid, 'service_input': {
            'orders': [{'amount': '1.25', 'category': 'books', 'private_key': 'not-allowed'}]}}, schema)


def test_public_purchase_omits_internal_identity_and_control_plane_metadata():
    import asyncio
    import json
    from examples.commerce.node import LocalMarketplaceClient
    class InternalBridge:
        def request(self, method, arguments):
            return {'purchase_id': 'purchase_1', 'state': 'delivered',
                    'user_id': 'internal-user', 'policy_decision_id': 'internal-policy',
                    'metadata': {'receipt_signing_key': 'internal-fixture-key'},
                    'service_result': {'count': 1, 'total': '1.00', 'by_category': {'books': '1.00'}}}
    result = asyncio.run(LocalMarketplaceClient(InternalBridge()).call_tool(
        'execute_clink_purchase', {'preview_id': 'preview_1'}))
    assert 'user_id' not in result.structuredContent
    assert 'policy_decision_id' not in result.structuredContent
    assert 'metadata' not in result.structuredContent
    assert result.structuredContent['service_result']['total'] == '1.00'
    assert json.loads(result.content[0].text) == result.structuredContent
