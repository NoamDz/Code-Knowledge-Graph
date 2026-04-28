"""Per-tool invocation telemetry for dogfood measurement.

Writes one JSONL line per tool call to the path in CODE_GRAPH_TELEMETRY_LOG.
When the env var is unset, all overhead is one env lookup and nothing else.

Schema (one JSON object per line):
    {
      "ts": "2026-04-25T14:32:01.234Z",
      "tool": "explain_flow",
      "args": {"endpoint": "/api/auth/login", "escape_hatch": false},
      "duration_ms": 142,
      "result_chars": 1820,
      "error": null    // or {"type": "...", "message": "..."} on raise
    }

This satisfies 07_proposal.md C9: tool-invocation attempts are logged separately
from useful outcomes — a downstream dogfood scorer joins these against agent
trajectories to compute attempt vs. useful-outcome ratios per tool.
"""

from __future__ import annotations

import functools
import inspect
import json
import os
import time
from datetime import datetime, timezone
from typing import Any, Callable


def _log_path() -> str | None:
    return os.environ.get("CODE_GRAPH_TELEMETRY_LOG")


def _serialize_args(bound_args: inspect.BoundArguments) -> dict[str, Any]:
    out: dict[str, Any] = {}
    for k, v in bound_args.arguments.items():
        if isinstance(v, (str, int, float, bool)) or v is None:
            out[k] = v
        else:
            try:
                out[k] = repr(v)[:200]
            except Exception:
                out[k] = "<unrepr>"
    return out


def _emit(record: dict[str, Any]) -> None:
    path = _log_path()
    if not path:
        return
    try:
        with open(path, "a", encoding="utf-8") as f:
            f.write(json.dumps(record, separators=(",", ":")) + "\n")
    except OSError:
        # Telemetry must never break a tool call.
        pass


def traced(tool_name: str) -> Callable:
    """Decorator. Logs invocation attempt, duration, result size, and any error."""

    def decorator(fn: Callable) -> Callable:
        sig = inspect.signature(fn)

        @functools.wraps(fn)
        def wrapper(*args, **kwargs):
            if _log_path() is None:
                return fn(*args, **kwargs)

            start = time.monotonic()
            try:
                bound = sig.bind(*args, **kwargs)
                bound.apply_defaults()
                arg_record = _serialize_args(bound)
            except TypeError:
                arg_record = {"_bind_failed": True}

            err: dict[str, str] | None = None
            result: Any = None
            try:
                result = fn(*args, **kwargs)
                return result
            except Exception as e:
                err = {"type": type(e).__name__, "message": str(e)[:300]}
                raise
            finally:
                duration_ms = int((time.monotonic() - start) * 1000)
                result_chars = len(result) if isinstance(result, str) else None
                _emit({
                    "ts": datetime.now(timezone.utc).isoformat(timespec="milliseconds").replace("+00:00", "Z"),
                    "tool": tool_name,
                    "args": arg_record,
                    "duration_ms": duration_ms,
                    "result_chars": result_chars,
                    "error": err,
                })

        return wrapper

    return decorator
