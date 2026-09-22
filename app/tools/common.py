from collections.abc import Callable
from functools import wraps
import inspect
import json
import logging
import time
from typing import Any, TypeVar

from app.models.schemas import fail, ok
from app.turn_metrics import (
    current_turn_id,
    dedupe_tool_call,
    get_agent,
    is_completed,
    log_tool_end,
    log_tool_start,
    mark,
    record_tool_call,
    set_tool,
)

F = TypeVar("F", bound=Callable[..., Any])

logger = logging.getLogger("pharmacy-api.tools")


def _bound_args(function: Callable, args: tuple, kwargs: dict) -> dict:
    """Resolve positional + keyword args to a {param_name: value} dict,
    independent of whether the caller passed args positionally or by
    keyword (fast_path calls tools directly; ADK invokes them from parsed
    function_call args as kwargs). Used both for the idempotency key and
    for the human-readable [TOOL_START] input= log."""

    try:
        bound = inspect.signature(function).bind(*args, **kwargs)
        bound.apply_defaults()
        return bound.arguments
    except TypeError:
        # Signature mismatch -- let the real call raise its own error
        # instead of masking it behind a key-building failure.
        return {"args": args, "kwargs": kwargs}


def _call_key(payload: dict) -> str:
    """Stable key for "same tool + same arguments"."""

    return json.dumps(payload, sort_keys=True, default=str)


def _format_input(payload: dict) -> str:
    """Compact, readable [TOOL_START] input= value, e.g.
    'query="Dolo 650", category=None'."""

    return ", ".join(
        f"{key}={value!r}" for key, value in payload.items()
    )


def safe_tool(function: F) -> F:
    """Return deterministic tool errors in the shared public result format.

    Every tool (care and commerce alike) passes through here, so this is
    also the single place that enforces per-turn duplicate protection for
    tool execution:
      - a tool call for a turn that's already completed is refused
        outright (the model can't be un-called, but the DB shouldn't be
        mutated again for a response that's already gone out);
      - a tool called twice in the same turn with the same arguments
        executes only once -- the second call returns the first call's
        cached result instead of re-running the function body.
    This is also the single place actual tool *execution* is timed and
    logged -- one line per real Python call, tagged with whichever
    turn_id is current (see turn_metrics.current_turn_id).
    """
    @wraps(function)
    def wrapped(*args: Any, **kwargs: Any) -> dict:
        turn_id = current_turn_id()
        agent = get_agent(turn_id)

        if is_completed(turn_id):
            set_tool(turn_id, function.__name__)
            mark(
                turn_id,
                "tool_exec",
                status="duplicate_suppressed",
            )
            log_tool_start(
                turn_id, agent, function.__name__,
                _format_input(_bound_args(function, args, kwargs)),
            )
            log_tool_end(
                turn_id, agent, function.__name__,
                0.0, "duplicate_suppressed",
            )
            return fail(
                "DUPLICATE_SUPPRESSED",
                "This turn has already completed; ignoring late tool call.",
            )

        payload = _bound_args(function, args, kwargs)
        # Idempotency is per *tool call*. Arguments alone are not unique:
        # view_cart(user_id) and checkout_cart(user_id) must never share a
        # cache entry merely because their input happens to be identical.
        call_key = _call_key({"tool": function.__name__, "arguments": payload})
        tool_input = _format_input(payload)

        cached = dedupe_tool_call(turn_id, call_key)

        if cached is not None:
            # Suppressed *before* execution: the cache lookup above is the
            # only thing that ran for this call -- function(...) itself is
            # never invoked on a duplicate.
            set_tool(turn_id, function.__name__)
            mark(
                turn_id,
                "tool_exec",
                status="duplicate_suppressed",
            )
            log_tool_start(turn_id, agent, function.__name__, tool_input)
            log_tool_end(
                turn_id, agent, function.__name__,
                0.0, "duplicate_suppressed",
            )
            return cached

        set_tool(turn_id, function.__name__)
        log_tool_start(turn_id, agent, function.__name__, tool_input)
        started = time.monotonic()

        try:
            result = ok(function(*args, **kwargs))
            # Persist a completed real execution. Suppressed calls above do
            # not reach this line and therefore cannot repeat mutations.
            from app.database import database
            database.save()
            duration = time.monotonic() - started
            mark(
                turn_id,
                "tool_exec",
                status="ok",
                tool_time=duration,
            )
            log_tool_end(turn_id, agent, function.__name__, duration, "success")
            record_tool_call(turn_id, call_key, result)
            return result
        except ValueError as exc:
            duration = time.monotonic() - started
            result = fail("VALIDATION_ERROR", str(exc))
            mark(
                turn_id,
                "tool_exec",
                status="validation_error",
                tool_time=duration,
            )
            log_tool_end(
                turn_id, agent, function.__name__,
                duration, "validation_error",
            )
            record_tool_call(turn_id, call_key, result)
            return result
        except Exception:
            duration = time.monotonic() - started
            result = fail("INTERNAL_ERROR", "The operation could not be completed")
            mark(
                turn_id,
                "tool_exec",
                status="internal_error",
                tool_time=duration,
            )
            log_tool_end(
                turn_id, agent, function.__name__,
                duration, "internal_error",
            )
            record_tool_call(turn_id, call_key, result)
            return result
    return wrapped  # type: ignore[return-value]


def text(value: str, field: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{field} is required")
    return value.strip()


def amount(value: int, field: str = "quantity") -> int:
    if not isinstance(value, int) or value < 1:
        raise ValueError(f"{field} must be a positive integer")
    return value
