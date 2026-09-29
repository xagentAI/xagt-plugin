"""One sequential Marketplace process owns the persistent review tenant."""
from pathlib import Path
import json
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "apps/marketplace"))

from agentonomy_commerce.runtime import ReviewRuntime


METHODS = frozenset({"search", "preview", "execute", "purchase", "snapshot"})
# The public HTTP body remains capped at 256 KiB. Internal JSON escaping can
# expand a valid 128 KiB UTF-8 CSV (especially non-BMP characters) to 384 KiB.
MAX_FRAME_BYTES = 1_048_576


def main():
    with ReviewRuntime(Path(sys.argv[1]), int(sys.argv[2])) as runtime:
        while True:
            line = sys.stdin.buffer.readline(MAX_FRAME_BYTES + 1)
            if not line:
                return
            if len(line) > MAX_FRAME_BYTES or not line.endswith(b"\n"):
                return
            request = {}
            try:
                request = json.loads(line)
                if not isinstance(request, dict):
                    request = {}
                    raise ValueError("invalid frame")
                method = request["method"]
                if method not in METHODS or not isinstance(request.get("arguments", {}), dict):
                    raise ValueError("invalid operation")
                result = getattr(runtime, method)(**request.get("arguments", {}))
            except KeyError:
                result = {"_error": "not_found"}
            except (ValueError, TypeError) as exc:
                result = {"_error": "idempotency_conflict" if str(exc) == "idempotency_conflict" else "invalid_input"}
            except Exception:
                result = {"_error": "operation_unavailable"}
            print(json.dumps({"id": request.get("id"), "result": result}, default=str), flush=True)


if __name__ == "__main__":
    main()
