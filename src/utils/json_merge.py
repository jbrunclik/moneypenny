"""JSON Merge Patch (RFC 7396) over parsed JSON objects."""

from typing import Any


def merge_patch(base: dict[str, Any], patch: dict[str, Any]) -> dict[str, Any]:
    """Recursively merge `patch` into `base`, returning a new dict.

    Nested objects merge rather than replace, so updating one field of
    `progress.bench` does not drop `progress.squat`. An explicit null removes
    the key, which is the only way to delete a field without a full rewrite.
    """
    out = dict(base)
    for k, v in patch.items():
        if v is None:
            out.pop(k, None)
        elif isinstance(v, dict) and isinstance(out.get(k), dict):
            out[k] = merge_patch(out[k], v)
        else:
            out[k] = v
    return out
