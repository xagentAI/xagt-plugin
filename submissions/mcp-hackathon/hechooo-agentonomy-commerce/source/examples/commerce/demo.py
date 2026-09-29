"""Buy a service through the Node MCP and print verifiable rehearsal evidence."""
from __future__ import annotations

import asyncio
from datetime import timedelta
from decimal import Decimal
import json
from pathlib import Path
import sys

from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client

ROOT = Path(__file__).resolve().parents[2]
ORDERS = {'orders': [
    {'amount': '12.50', 'category': 'books'},
    {'amount': '7.25', 'category': 'food'},
    {'amount': '2.50', 'category': 'books'},
]}


async def call(session, name, arguments=None):
    response = await session.call_tool(name, arguments or {})
    if response.isError:
        raise RuntimeError(f'{name}: ' + ' '.join(getattr(x, 'text', '') for x in response.content))
    if response.structuredContent is not None:
        return response.structuredContent
    return json.loads(next(x.text for x in response.content if x.type == 'text'))


async def run_demo():
    params = StdioServerParameters(command=sys.executable,
        args=['-m', 'examples.commerce.node'], cwd=str(ROOT))
    async with stdio_client(params) as (read, write):
        async with ClientSession(read, write, read_timeout_seconds=timedelta(seconds=60)) as session:
            initialization = await session.initialize()
            tools = await session.list_tools()
            before = await call(session, 'clink_node_status')
            catalog = await call(session, 'search_clink_services', {'query': 'analysis'})
            offering = min(catalog['items'], key=lambda item: Decimal(item['price_usd']))
            rejected = await session.call_tool('create_clink_purchase_preview', {
                'offering_id': offering['offering_id'],
                'service_input': {**ORDERS, 'user_id': 'another-user'},
            })
            preview = await call(session, 'create_clink_purchase_preview',
                                 {'offering_id': offering['offering_id'], 'service_input': ORDERS})
            purchase = await call(session, 'execute_clink_purchase', {'preview_id': preview['preview_id']})
            after = await call(session, 'clink_node_status')
            replay = await call(session, 'execute_clink_purchase', {'preview_id': preview['preview_id']})
            retrieved = await call(session, 'get_clink_purchase', {'purchase_id': purchase['purchase_id']})
            final = await call(session, 'clink_node_status')
            service_result = purchase.get('service_result')
            checks = {
                'identity_override_rejected': rejected.isError is True,
                'received_result': purchase.get('state') == 'delivered' and bool(service_result),
                'replay_did_not_charge': replay['purchase_id'] == purchase['purchase_id']
                    and after['settlement_submissions'] == final['settlement_submissions'] == 1,
                'result_retrievable': bool(retrieved.get('service_result')),
                'budget_accounted': Decimal(final['used_amount_usdc']) == Decimal('0.30')
                    and Decimal(final['reserved_amount_usdc']) == 0,
            }
            if not all(checks.values()):
                raise AssertionError(json.dumps({'checks': checks, 'purchase': purchase, 'final': final}))
            return {'project': 'Agentonomy Commerce', 'mode': 'local-simulation', 'real_funds': False,
                    'mcp_server': initialization.serverInfo.name,
                    'tools': [tool.name for tool in tools.tools],
                    'before': before, 'preview': preview, 'purchase': purchase, 'service_result': service_result,
                    'after': final, 'checks': checks}


def main():
    print(json.dumps(asyncio.run(run_demo()), indent=2, ensure_ascii=False))


if __name__ == '__main__':
    main()
