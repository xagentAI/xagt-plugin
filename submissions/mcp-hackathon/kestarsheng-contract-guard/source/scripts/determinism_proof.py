# -*- coding: utf-8 -*-
"""Determinism proof: Contract Guard vs. an LLM asked the same question twice.

Replays the same contract-diff request twice through the deterministic engine
and (optionally) asks an OpenAI-compatible LLM the same breaking-change question
twice, then compares agreement. Run without arguments for the deterministic
half only (no API key needed).

Usage:
    python scripts/determinism_proof.py
    LLM_API_KEY=sk-... LLM_BASE_URL=... python scripts/determinism_proof.py --with-llm
"""
from __future__ import annotations

import hashlib
import json
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

OLD_SPEC = {
    "openapi": "3.0.3",
    "info": {"title": "Users API", "version": "1.4.0"},
    "paths": {
        "/users": {
            "get": {
                "parameters": [
                    {"name": "limit", "in": "query", "schema": {"type": "integer"}}
                ],
                "responses": {
                    "200": {
                        "description": "ok",
                        "content": {
                            "application/json": {
                                "schema": {"$ref": "#/components/schemas/UserList"}
                            }
                        },
                    }
                },
            }
        },
        "/users/{id}": {
            "delete": {"responses": {"204": {"description": "deleted"}}}
        },
    },
    "components": {
        "schemas": {
            "User": {
                "type": "object",
                "properties": {
                    "id": {"type": "integer"},
                    "email": {"type": "string"},
                    "role": {
                        "type": "string",
                        "enum": ["admin", "user", "guest"],
                    },
                },
                "required": ["id", "email"],
            },
            "UserList": {"type": "array", "items": {"$ref": "#/components/schemas/User"}},
        }
    },
}

NEW_SPEC = {
    "openapi": "3.0.3",
    "info": {"title": "Users API", "version": "2.0.0"},
    "paths": {
        "/users": {
            "get": {
                "parameters": [
                    {"name": "limit", "in": "query", "schema": {"type": "integer"}}
                ],
                "responses": {
                    "200": {
                        "description": "ok",
                        "content": {
                            "application/json": {
                                "schema": {"$ref": "#/components/schemas/UserList"}
                            }
                        },
                    }
                },
            }
        },
        "/users/{id}": {
            "delete": {"responses": {"204": {"description": "deleted"}}}
        },
    },
    "components": {
        "schemas": {
            "User": {
                "type": "object",
                "properties": {
                    "id": {"type": "integer"},
                    "email": {"type": "string"},
                    "role": {
                        "type": "string",
                        "enum": ["admin", "user", "guest", "owner"],
                    },
                },
                "required": ["id", "email", "role"],
            },
            "UserList": {"type": "array", "items": {"$ref": "#/components/schemas/User"}},
        }
    },
}


def deterministic_diff(n: int) -> dict:
    """Run the pure engine (no HTTP, no LLM) n times; return bodies + signature."""
    from app.diff_core import detect_changes  # type: ignore

    bodies = []
    for _ in range(n):
        result = detect_changes(
            old_raw=json.dumps(OLD_SPEC),
            new_raw=json.dumps(NEW_SPEC),
            fmt="openapi",
            use_llm=False,
        )
        bodies.append(
            json.dumps(result.as_dict(), sort_keys=True, ensure_ascii=False)
        )
    return {"bodies": bodies, "signature": hashlib.sha256(bodies[0].encode()).hexdigest()}


def llm_ask(prompt: str, settings) -> str:
    import httpx  # type: ignore

    url = settings.llm_base_url.rstrip("/") + "/chat/completions"
    headers = {
        "Authorization": f"Bearer {settings.llm_api_key}",
        "Content-Type": "application/json",
    }
    payload = {
        "model": settings.llm_model or "deepseek-chat",
        "messages": [{"role": "user", "content": prompt}],
        "temperature": 0.2,
        "max_tokens": 600,
    }
    with httpx.Client(timeout=settings.llm_timeout_seconds) as client:
        resp = client.post(url, headers=headers, json=payload)
        resp.raise_for_status()
        return resp.json()["choices"][0]["message"]["content"]


def llm_compare(settings) -> dict:

    prompt = (
        "Compare these two OpenAPI contract versions and list every breaking "
        "change.\n\nV1.4.0:\n"
        + json.dumps(OLD_SPEC, indent=2)
        + "\n\nV2.0.0:\n"
        + json.dumps(NEW_SPEC, indent=2)
    )
    answers = [llm_ask(prompt, settings), llm_ask(prompt, settings)]
    identical = answers[0] == answers[1]
    return {
        "identical": identical,
        "len_a": len(answers[0]),
        "len_b": len(answers[1]),
        "answer_a": answers[0][:400],
        "answer_b": answers[1][:400],
        "sha256_a": hashlib.sha256(answers[0].encode()).hexdigest(),
        "sha256_b": hashlib.sha256(answers[1].encode()).hexdigest(),
    }


def main() -> int:
    print("=== Contract Guard determinism proof ===")
    print("Pair: Users API v1.4.0 -> v2.0.0 (enum value added + required field added)\n")

    det = deterministic_diff(3)
    identical = len(set(det["bodies"])) == 1
    print(f"Deterministic engine, 3 replays of POST /v1/diff:")
    print(f"  responses byte-identical : {identical}")
    print(f"  sha256 of response       : {det['signature'][:16]}...")
    b = json.loads(det["bodies"][0])
    print(f"  breaking={b['breaking']} breaking_count={b['breaking_count']}")
    for f in b["findings"]:
        print(
            f"    - [{f['severity']}] {f['change_type']} {f['location']} "
            f"(id={f['id']})"
        )
    print()

    if "--with-llm" in sys.argv:
        from app.config import get_settings  # type: ignore

        llm = llm_compare(get_settings())
        print(f"LLM asked the same question twice at temperature 0.2:")
        print(f"  answers identical        : {llm['identical']}")
        print(f"  sha256 run 1             : {llm['sha256_a'][:16]}...")
        print(f"  sha256 run 2             : {llm['sha256_b'][:16]}...")
        print(f"  answer 1 (first 400 ch)  : {llm['answer_a'][:400]!r}")
        print(f"  answer 2 (first 400 ch)  : {llm['answer_b'][:400]!r}")

    return 0 if identical else 2


if __name__ == "__main__":
    raise SystemExit(main())