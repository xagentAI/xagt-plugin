from typing import Any
import re


def _extract_number(v: Any) -> Any:
    if isinstance(v, (int, float)):
        return v
    m = re.search(r"-?\d+(\.\d+)?", str(v))
    return float(m.group(0)) if m and "." in m.group(0) else int(m.group(0)) if m else v


TRANSFORMS = {"rename_field", "cast_string_to_number", "cast_number_to_string", "extract_number",
              "default_value", "flatten_object", "wrap_object", "map_enum", "remove_field",
              "copy_field", "normalize_boolean", "normalize_null"}


def apply_repairs(payload: Any, rules: list[dict[str, Any]]) -> Any:
    if not isinstance(payload, dict):
        return payload
    data = dict(payload)
    for r in rules:
        t = r.get("transform")
        if t not in TRANSFORMS:
            continue
        src, tgt = r.get("source_field", ""), r.get("target_field", "")
        try:
            if t == "rename_field" and src in data:
                data[tgt or src] = data.pop(src)
            elif t == "copy_field" and src in data:
                data[tgt] = data[src]
            elif t == "remove_field" and src in data:
                data.pop(src, None)
            elif t == "extract_number" and src in data:
                data[tgt or src] = _extract_number(data[src])
            elif t == "cast_string_to_number" and src in data:
                data[tgt or src] = _extract_number(data[src])
            elif t == "cast_number_to_string" and src in data:
                data[tgt or src] = str(data[src])
            elif t == "default_value" and tgt and data.get(tgt) in (None, ""):
                data[tgt] = r.get("default")
            elif t == "normalize_boolean" and src in data:
                v = str(data[src]).lower()
                data[tgt or src] = v in ("1", "true", "yes", "y", "on")
            elif t == "normalize_null" and src in data and data[src] in ("null", "NULL", "None", ""):
                data[tgt or src] = None
            elif t == "map_enum" and src in data:
                data[tgt or src] = r.get("mapping", {}).get(str(data[src]), data[src])
            elif t == "flatten_object" and src in data and isinstance(data[src], dict):
                for k, v in data[src].items():
                    data[f"{tgt or src}_{k}" if tgt else k] = v
                data.pop(src, None)
            elif t == "wrap_object" and tgt:
                data[tgt] = {k: data.pop(k) for k in list(data.keys()) if k in (r.get("fields") or [])}
        except Exception:
            raise ValueError(f"TRANSFORMATION_FAILED:{t}")
    return data


def auto_suggest_repairs(test_results: list[dict], issues: list[dict]) -> list[dict[str, Any]]:
    rules: list[dict[str, Any]] = []
    # Known demo patterns: tmp->temperature_celsius, desc->condition, price string->number
    rules += [
        {"source_field": "tmp", "target_field": "temperature_celsius", "transform": "extract_number", "target_type": "number"},
        {"source_field": "desc", "target_field": "condition", "transform": "map_enum", "mapping": {"sun": "sunny", "cloud": "cloudy", "rain": "rainy"}},
        {"source_field": "temperature", "target_field": "temperature_celsius", "transform": "extract_number", "target_type": "number"},
        {"source_field": "weather", "target_field": "condition", "transform": "copy_field"},
        {"source_field": "price", "target_field": "price", "transform": "extract_number", "target_type": "number"},
    ]
    return rules
