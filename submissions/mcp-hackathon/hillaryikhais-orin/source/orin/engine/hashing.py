import hashlib, json

def h(v):
    return hashlib.sha256(json.dumps(v, default=str, sort_keys=True).encode()).hexdigest()

def short(v):
    return h(v)[:8].upper()

SECRET = "orin-dev-secret-v1"
