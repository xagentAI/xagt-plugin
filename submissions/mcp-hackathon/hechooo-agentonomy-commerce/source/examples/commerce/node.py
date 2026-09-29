"""Run the shipped Node MCP gateway against an isolated local Commerce demo.

The only public transport is stdio. Every process lifetime creates a new demo
wallet and simulated mandate. This module cannot connect to a real chain.
"""
from __future__ import annotations

import asyncio
import json
import os
from pathlib import Path
import selectors
import subprocess
import sys
import tempfile
import threading
import time

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / 'apps/core'))
sys.path.insert(0, str(ROOT / 'apps/node'))

from mcp import types
from mcp.server.stdio import stdio_server
from clink_node.mcp_gateway import create_mcp_server
from clink_node.mcp_proxy import McpToolProxy, NativeTool


def object_schema(properties, required=()):
    return {'type': 'object', 'properties': properties, 'required': list(required),
            'additionalProperties': False}


IDENTIFIER = {'type': 'string', 'minLength': 1, 'maxLength': 160}
TOOL_SCHEMAS = {
    'search_clink_services': object_schema({'query': {'type': 'string', 'maxLength': 200}}),
    'get_clink_service_details': object_schema({'offering_id': IDENTIFIER}, ['offering_id']),
    'create_clink_purchase_preview': object_schema({
        'offering_id': IDENTIFIER,
        'service_input': object_schema({'orders': {
            'type': 'array', 'minItems': 1, 'maxItems': 1000,
            'items': object_schema({
                'amount': {'type': 'string', 'maxLength': 15,
                           'pattern': r'^(0|[1-9][0-9]{0,11})(\.[0-9]{1,2})?$'},
                'category': {'type': 'string', 'minLength': 1, 'maxLength': 80},
            }, ['amount', 'category']),
        }}, ['orders']),
    }, ['offering_id', 'service_input']),
    'execute_clink_purchase': object_schema({'preview_id': IDENTIFIER}, ['preview_id']),
    'get_clink_purchase': object_schema({'purchase_id': IDENTIFIER}, ['purchase_id']),
}
METHODS = {
    'search_clink_services': ('search', 'Discover the local paid order-analysis services.'),
    'get_clink_service_details': ('details', 'Read the service price and simulated payment scope.'),
    'create_clink_purchase_preview': ('preview', 'Lock the quote and input under the demo user identity.'),
    'execute_clink_purchase': ('execute', 'Execute using the signed demo mandate and Core budget. Simulated settlement only.'),
    'get_clink_purchase': ('purchase', 'Read existing purchase status and available service result without charging.'),
}


class MarketplaceBridge:
    def __init__(self, state_dir: Path, *, worker_module="examples.commerce.market_worker", worker_args=()):
        env = {key: value for key, value in os.environ.items()
               if key in {'PATH', 'SYSTEMROOT', 'TMPDIR', 'LANG', 'LC_ALL'}}
        env['PYTHONPATH'] = str(ROOT)
        env['PYTHONUNBUFFERED'] = '1'
        self.process = subprocess.Popen(
            [sys.executable, '-m', worker_module, str(state_dir), *worker_args],
            cwd=ROOT, env=env, stdin=subprocess.PIPE, stdout=subprocess.PIPE,
            stderr=sys.stderr, bufsize=-1,
        )
        self.lock = threading.Lock()
        self.broken = False
        self.request_id = 0
        self.buffer = b''

    def request(self, method, arguments=None):
        with self.lock:
            if self.broken or self.process.poll() is not None:
                raise RuntimeError('local Marketplace channel is broken or exited')
            self.request_id += 1
            request = {'id': self.request_id, 'method': method, 'arguments': arguments or {}}
            try:
                self.process.stdin.write((json.dumps(request) + '\n').encode())
                self.process.stdin.flush()
                response = self._read_response()
                if not isinstance(response, dict) or response.get('id') != self.request_id:
                    raise RuntimeError('local Marketplace returned a mismatched response id')
                if 'result' not in response and 'error' not in response:
                    raise RuntimeError('local Marketplace returned invalid response data')
            except (OSError, ValueError, RuntimeError) as exc:
                self.broken = True
                if self.process.poll() is None:
                    self.process.terminate()
                self.close()
                raise
            if 'error' in response:
                raise RuntimeError(response['error'])
            return response['result']

    def _read_response(self):
        deadline = time.monotonic() + 45
        with selectors.DefaultSelector() as selector:
            selector.register(self.process.stdout, selectors.EVENT_READ)
            while b'\n' not in self.buffer:
                remaining = deadline - time.monotonic()
                if remaining <= 0 or not selector.select(timeout=remaining):
                    raise TimeoutError('local demo outcome is unknown; do not create another purchase')
                chunk = os.read(self.process.stdout.fileno(), 65536)
                if not chunk:
                    raise RuntimeError('local Marketplace worker stopped before replying')
                self.buffer += chunk
                if len(self.buffer) > 1_048_576:
                    raise RuntimeError('local Marketplace response exceeds the size limit')
        line, self.buffer = self.buffer.split(b'\n', 1)
        return json.loads(line)

    def close(self):
        self.broken = True
        if self.process.stdin and not self.process.stdin.closed:
            try:
                self.process.stdin.close()
            except (BrokenPipeError, OSError):
                pass
        try:
            self.process.wait(timeout=5)
        except subprocess.TimeoutExpired:
            self.process.terminate()
            try:
                self.process.wait(timeout=5)
            except subprocess.TimeoutExpired:
                self.process.kill()
                self.process.wait(timeout=5)
        if self.process.stdout and not self.process.stdout.closed:
            self.process.stdout.close()


def public_result(name, result):
    """Expose purchase evidence without Core identity or internal control data."""
    if name == 'create_clink_purchase_preview':
        allowed = {'preview_id', 'offering_id', 'state', 'expires_at', 'created_at',
                   'payment', 'payment_capability', 'execution_mode', 'quote_hash', 'input_hash'}
        return {key: value for key, value in result.items() if key in allowed}
    if name in {'execute_clink_purchase', 'get_clink_purchase'}:
        allowed = {'purchase_id', 'preview_id', 'offering_id', 'state', 'execution_mode',
                   'reason_code', 'receipt_id', 'input_hash', 'output_hash',
                   'created_at', 'updated_at', 'service_result'}
        return {key: value for key, value in result.items() if key in allowed}
    return result


class LocalMarketplaceClient:
    def __init__(self, bridge):
        self.bridge = bridge

    async def list_tools(self):
        return [types.Tool(name=name, description=METHODS[name][1], inputSchema=schema)
                for name, schema in TOOL_SCHEMAS.items()]

    async def call_tool(self, name, arguments):
        result = await asyncio.to_thread(self.bridge.request, METHODS[name][0], arguments)
        result = public_result(name, result)
        return types.CallToolResult(content=[types.TextContent(type='text', text=json.dumps(result))],
                                    structuredContent=result)


async def serve() -> None:
    with tempfile.TemporaryDirectory(prefix='agentonomy-commerce-') as state:
        bridge = MarketplaceBridge(Path(state))
        try:
            async def status(arguments):
                del arguments
                snapshot = await asyncio.to_thread(bridge.request, 'snapshot')
                return {**snapshot, 'status': 'ready', 'mode': 'local-simulation',
                        'real_funds': False, 'prediction_markets': 'disabled'}

            native = NativeTool(types.Tool(name='clink_node_status',
                description='Read local demo budget and settlement counters. No real funds.',
                inputSchema=object_schema({})), status)
            proxy = McpToolProxy({'marketplace': LocalMarketplaceClient(bridge)},
                                 native_tools={'clink_node_status': native})
            server = create_mcp_server(proxy)
            async with stdio_server() as (read, write):
                await server.run(read, write, server.create_initialization_options())
        finally:
            bridge.close()


if __name__ == '__main__':
    asyncio.run(serve())
