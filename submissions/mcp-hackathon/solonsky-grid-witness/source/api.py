"""Stateless HTTP capability; no input persistence or outbound API calls."""
import json
import os
import re
from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse
from core import inspect_plan, compare_budget, summary

router = APIRouter()
SLUG = 'solonsky-grid-witness'
MAX_BODY = 2048

def review_commit():
    value = os.environ.get('SOURCE_COMMIT', '')
    return value if re.fullmatch(r'[a-f0-9]{40}', value) else None

@router.get('/health')
def health():
    commit = review_commit()
    return JSONResponse({'status': 'ok' if commit else 'unversioned', 'commit': commit}, status_code=200 if commit else 503)

@router.get('/.well-known/xagent-verification.json')
def proof():
    return {'schemaVersion': 1, 'slug': SLUG, 'commit': review_commit()}

@router.get('/v1/benchmark')
def benchmark_summary():
    return summary()

async def body(request):
    if request.headers.get('content-type', '').split(';')[0].strip().lower() != 'application/json':
        raise ValueError('Content-Type must be application/json')
    data = bytearray()
    async for chunk in request.stream():
        data.extend(chunk)
        if len(data) > MAX_BODY:
            raise ValueError('Request body exceeds 2048 bytes')
    obj = json.loads(data, parse_constant=lambda _: (_ for _ in ()).throw(ValueError('Nonfinite JSON numbers are not allowed')))
    if not isinstance(obj, dict):
        raise ValueError('JSON body must be an object')
    return obj

@router.post('/v1/inspect-plan')
async def inspect(request: Request):
    try:
        obj = await body(request)
        if set(obj) != {'bits'}:
            raise ValueError('Expected exactly one field: bits')
        return inspect_plan(obj['bits'])
    except (ValueError, UnicodeError):
        return JSONResponse({'error': 'invalid_request', 'message': 'Use application/json with exactly {"bits":[0,0,0,0,0,0]}; six integer binary values; max 2048 bytes.'}, status_code=400)

@router.post('/v1/compare-budget')
async def budget(request: Request):
    try:
        obj = await body(request)
        if set(obj) != {'budget'}:
            raise ValueError('Expected exactly one field: budget')
        return compare_budget(obj['budget'])
    except (ValueError, UnicodeError):
        return JSONResponse({'error': 'invalid_request', 'message': 'Use application/json with exactly {"budget":20}; integer 0..27 in synthetic units; max 2048 bytes.'}, status_code=400)
