"""Process-isolated Marketplace for the local demo; stdout is JSON RPC only."""
from __future__ import annotations

import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / 'apps/marketplace'))
from examples.commerce.marketplace import CommerceRuntime

METHODS = frozenset({'search', 'details', 'preview', 'execute', 'purchase', 'snapshot'})


def main() -> None:
    with CommerceRuntime(Path(sys.argv[1])) as runtime:
        for line in sys.stdin:
            request = {}
            try:
                request = json.loads(line)
                if not isinstance(request, dict):
                    request = {}
                    raise ValueError('invalid protocol frame')
                method = request['method']
                if method not in METHODS:
                    raise ValueError('unknown local demo operation')
                result = getattr(runtime, method)(**request.get('arguments', {}))
                response = {'id': request['id'], 'result': result}
            except Exception as exc:
                response = {'id': request.get('id'), 'error': 'local_commerce_operation_failed', 'type': type(exc).__name__}
            print(json.dumps(response, default=str), flush=True)


if __name__ == '__main__':
    main()
