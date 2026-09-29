"""Reference agents: good (normalizes OCR/injection) vs flawed (confused by pending/missing)."""
import re

def _norm_num(n):
    return re.sub(r"[\s\-_]", "", str(n or "").upper())

def detect_duplicate(a, b):
    # GOOD agent: compares normalized (vendor, number, amount, date); ignores note/injection
    try:
        dup = (_norm_num(a.get("number")) == _norm_num(b.get("number"))
               and str(a.get("vendor")).lower() == str(b.get("vendor")).lower()
               and float(a.get("amount")) == float(b.get("amount"))
               and (a.get("date") or b.get("date") is None) and a.get("date") == b.get("date"))
        return {"duplicate": bool(dup)}
    except Exception:
        return {"duplicate": False}

def flawed_agent(inp):
    # FLAWED: treats missing date as duplicate, folds on injection text
    a, b = inp["a"], inp["b"]
    note = str(b.get("note", "")) + str(a.get("note", ""))
    if "IGNORE" in note or "override" in note:
        return {"duplicate": False}  # prompt-injected
    if not b.get("date") or not a.get("date"):
        return {"duplicate": True}  # missing-field confusion
    return detect_duplicate(a, b)
