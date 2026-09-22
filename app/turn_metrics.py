"""Shared per-turn timing, logging, and duplicate protection for
router.py, main.py, and tools/common.py.

One physical turn (one user utterance -> one assistant response) is
tracked from a single in-memory registry keyed by turn_id, so all three
modules log against the same clock and the same `path`/`agent`/`tool`
labels, and agree on whether a turn has already been started, is still
open, or has already completed -- instead of each inventing its own
format or its own dedup rules. All three modules run in the same
process, so importing this module gives them the same singleton state --
no extra plumbing needed.

Duplicate protection has three layers, matching the three places a
duplicate can occur:
  - `try_start_turn` -- a turn_id is only ever started once. A live
    session redelivering the same finished-transcript event (or any
    other path producing a turn_id already seen) is refused here, before
    fast_path or any tool runs a second time for it.
  - `dedupe_tool_call` / `record_tool_call` -- within one turn, the same
    tool called with the same arguments only actually executes once;
    a repeat returns the cached result instead of hitting the database
    again.
  - `is_completed` / `end_turn` -- once a turn's single response has been
    sent, it is marked completed. Any further event or tool call that
    still carries that turn_id (a late/duplicate one) is refused/ignored
    rather than silently reprocessed.

`current_turn_id()` is a ContextVar rather than a plain module global so
concurrent voice connections (each its own asyncio task) each see only
their own "current" turn; asyncio copies the context into child
coroutines/tasks by default, so tool calls made while handling a turn see
the right id without any tool function signature changes.
"""

import contextvars
import logging
import time

logger = logging.getLogger("pharmacy-api.turns")

_current_turn: contextvars.ContextVar[str] = contextvars.ContextVar(
    "current_turn_id",
    default="-",
)

_turns: dict[str, dict] = {}

# turn_ids that have already been started/completed, kept for the life of
# the process so a late-arriving duplicate of an old turn_id is refused
# forever, not just for as long as its state happens to still be around.
_started_turn_ids: set[str] = set()
_completed_turn_ids: set[str] = set()

# Per-turn idempotency cache for tool calls: turn_id -> {call_key: result}.
_tool_call_cache: dict[str, dict[str, dict]] = {}


def _new_state() -> dict:
    return {
        "t0": time.monotonic(),
        "language": "-",
        "response_language": "-",
        "path": "-",
        "agent": "-",
        "tool": "-",
        "first_audio_sent": False,
        # (stage, elapsed_at_that_mark) in call order, used at end_turn to
        # find which stage took the longest since the previous one --
        # i.e. the actual slow step, not just cumulative elapsed time.
        "stage_history": [],
    }


def _state(turn_id: str) -> dict:
    return _turns.setdefault(turn_id, _new_state())


def turn_id_for(event) -> str:
    """One unique turn_id per transcript-received Event.

    ADK gives every Event a stable `.id`; router.py and main.py process
    the exact same Event object for a given transcript (main.py's loop
    consumes what router.py's live loop yields), so deriving turn_id from
    `event.id` gives both modules the identical id with no extra
    plumbing. The `id(event)` fallback only matters if ADK ever omits
    `.id` -- it's still deterministic for the two modules since they
    share the same object.
    """

    return event.id or f"obj{id(event)}"


def try_start_turn(turn_id: str) -> bool:
    """Start a turn if (and only if) it hasn't been started before.

    Returns True the first time -- the caller should proceed to process
    this turn. Returns False for a duplicate -- the caller should log
    status="duplicate_suppressed" and skip all processing for it (no
    fast_path, no tool call, no response).
    """

    if turn_id in _started_turn_ids:
        return False

    _started_turn_ids.add(turn_id)
    _turns[turn_id] = _new_state()
    _tool_call_cache[turn_id] = {}
    _current_turn.set(turn_id)
    logger.info("[TURN_START] turn_id=%s", turn_id)
    return True


def current_turn_id() -> str:
    return _current_turn.get()


def is_completed(turn_id: str) -> bool:
    return turn_id in _completed_turn_ids


def set_language(turn_id: str, language: str) -> None:
    _state(turn_id)["language"] = language


def set_response_language(turn_id: str, response_language: str) -> None:
    _state(turn_id)["response_language"] = response_language


def set_path(turn_id: str, path: str) -> None:
    """path: one of 'fast_path', 'agent', 'router_llm'."""
    _state(turn_id)["path"] = path


def get_path(turn_id: str) -> str:
    return _state(turn_id)["path"]


def set_agent(turn_id: str, agent: str) -> None:
    _state(turn_id)["agent"] = agent


def set_tool(turn_id: str, tool: str) -> None:
    _state(turn_id)["tool"] = tool


def get_agent(turn_id: str) -> str:
    return _state(turn_id)["agent"]


def get_tool(turn_id: str) -> str:
    return _state(turn_id)["tool"]


def mark_first_audio_sent(turn_id: str) -> None:
    _state(turn_id)["first_audio_sent"] = True


def has_first_audio(turn_id: str) -> bool:
    return _state(turn_id)["first_audio_sent"]


def elapsed(turn_id: str) -> float:
    """Seconds since this turn's transcript was received."""
    return time.monotonic() - _state(turn_id)["t0"]


def mark(turn_id: str, stage: str, status: str = "ok", **fields) -> None:
    """Log one structured stage line.

    Every line always carries turn_id | language | path | agent | tool |
    duration | status, in that order, plus whatever extra named timing
    fields the caller passes (e.g. fast_path_time=0.012). `duration` is
    always the time elapsed since this turn's transcript was received
    (same clock as `elapsed()`) so every single log line -- not just the
    ones a caller remembers to time explicitly -- carries a duration,
    letting the slowest stage be read directly off the log without cross
    referencing separate fields.
    """

    state = _state(turn_id)
    now = elapsed(turn_id)

    rendered = " ".join(
        f"{key}={value:.3f}s" if isinstance(value, float) else f"{key}={value}"
        for key, value in fields.items()
    )

    logger.info(
        "[TURN %s] stage=%s turn_id=%s language=%s response_language=%s "
        "path=%s agent=%s tool=%s duration=%.3fs status=%s %s",
        turn_id,
        stage,
        turn_id,
        state["language"],
        state["response_language"],
        state["path"],
        state["agent"],
        state["tool"],
        now,
        status,
        rendered,
    )

    if status != "duplicate_suppressed":
        state["stage_history"].append((stage, now))


# ============================================================
# Bracket-style stage logs: [ROUTER] / [AGENT_START] / [AGENT_END] /
# [TOOL_START] / [TOOL_END] / [TURN_SUMMARY].
#
# These sit alongside `mark()` above rather than replacing it -- `mark()`
# still drives duplicate-suppression bookkeeping and the general
# structured trace. These give the same data in the compact per-stage
# form requested for reading a single request's Router -> Agent -> Tool
# flow top to bottom, and their durations are real, isolated stage
# timings (time.monotonic() deltas taken right before/after that specific
# stage) rather than `elapsed()`, which is cumulative since the turn's
# transcript was received.
# ============================================================


def log_router(turn_id: str, route: str, duration: float) -> None:
    """route: the agent(s)/path selected ('commerce', 'care', 'llm',
    'fast_path', 'no_match', ...). `duration` must be the router
    decision's own isolated time (e.g. a time.monotonic() delta measured
    only around the routing call), not elapsed() since turn start."""

    logger.info(
        "[ROUTER] turn_id=%s route=%s duration=%.3fs",
        turn_id,
        route,
        duration,
    )

    _state(turn_id)["path_trail"] = _state(turn_id).get("path_trail", []) + [
        "router"
    ]


def log_agent_start(turn_id: str, agent: str) -> None:
    logger.info(
        "[AGENT_START] turn_id=%s agent=%s",
        turn_id,
        agent,
    )

    state = _state(turn_id)
    state["_agent_started_at"] = time.monotonic()
    state["path_trail"] = state.get("path_trail", []) + [agent]


def log_agent_end(turn_id: str, agent: str, status: str = "ok") -> float:
    """Returns the agent's own isolated duration (time since the matching
    log_agent_start for this turn_id), not cumulative turn elapsed."""

    state = _state(turn_id)
    started = state.pop("_agent_started_at", None)
    duration = (time.monotonic() - started) if started is not None else 0.0

    logger.info(
        "[AGENT_END] turn_id=%s agent=%s duration=%.3fs status=%s",
        turn_id,
        agent,
        duration,
        status,
    )

    return duration


def log_tool_start(turn_id: str, agent: str, tool: str, tool_input) -> None:
    logger.info(
        "[TOOL_START] turn_id=%s agent=%s tool=%s input=%s",
        turn_id,
        agent,
        tool,
        tool_input,
    )

    state = _state(turn_id)
    trail = state.get("path_trail", [])

    # One "tools" hop in the breadcrumb regardless of how many individual
    # tools ran (each one's own name/timing is already in its own
    # [TOOL_START]/[TOOL_END] lines) -- keeps the summary trail as
    # router->agent->tools rather than router->agent->tools->tools->tools.
    if not trail or trail[-1] != "tools":
        state["path_trail"] = trail + ["tools"]


def log_tool_end(
    turn_id: str,
    agent: str,
    tool: str,
    duration: float,
    status: str,
) -> None:
    logger.info(
        "[TOOL_END] turn_id=%s agent=%s tool=%s duration=%.3fs status=%s",
        turn_id,
        agent,
        tool,
        duration,
        status,
    )


def log_first_audio(turn_id: str, duration: float) -> None:
    logger.info("[FIRST_AUDIO] turn_id=%s duration=%.3fs", turn_id, duration)


def log_agent_flow(turn_id: str, user_text: str, tool_name: str = "-") -> None:
    """Log the complete agent flow: USER → ROUTER → agent → tool → COMPLETE."""
    state = _state(turn_id)
    agent = state.get("agent", "-")
    tool_display = tool_name if tool_name and tool_name != "-" else "direct_response"
    logger.info(
        '[AGENT_FLOW] USER="%s" → ROUTER → %s → %s → COMPLETE',
        user_text,
        agent,
        tool_display,
    )


def dedupe_tool_call(turn_id: str, call_key: str) -> dict | None:
    """Return the cached result if this exact (turn_id, tool, args) call
    already ran this turn, else None (caller should execute it and then
    call record_tool_call)."""

    if turn_id == "-":
        # No real turn context (e.g. a call made outside any tracked
        # turn) -- nothing to bound the idempotency key to, so don't
        # risk false-positive suppression across unrelated calls.
        return None

    return _tool_call_cache.get(turn_id, {}).get(call_key)


def record_tool_call(turn_id: str, call_key: str, result: dict) -> None:
    if turn_id == "-":
        return

    _tool_call_cache.setdefault(turn_id, {})[call_key] = result


def end_turn(turn_id: str) -> None:
    """Mark a turn's single response as sent. After this, any further
    event or tool call still carrying this turn_id is a late/duplicate
    one and callers should refuse/ignore it (status="duplicate_suppressed")
    rather than reprocess it.

    Also emits one [TURN_SUMMARY] line identifying the slowest stage --
    the stage whose own gap since the previous mark was largest, not just
    whichever mark happened latest -- so a slow turn's bottleneck is
    readable without cross-referencing every stage line by hand.
    """

    if turn_id in _completed_turn_ids:
        return

    _completed_turn_ids.add(turn_id)
    _tool_call_cache.pop(turn_id, None)

    state = _turns.get(turn_id)

    if not state:
        return

    history = state["stage_history"]
    total = elapsed(turn_id)

    slowest_stage = "-"
    slowest_gap = -1.0
    previous_t = 0.0

    for stage_name, stage_t in history:
        gap = stage_t - previous_t
        if gap > slowest_gap:
            slowest_gap = gap
            slowest_stage = stage_name
        previous_t = stage_t

    flow = "->".join(state.get("path_trail", [])) or "-"

    logger.info(
        "[TURN_SUMMARY] turn_id=%s language=%s response_language=%s path=%s "
        "agent=%s tool=%s flow=%s total_turn_time=%.3fs total=%.3fs "
        "slowest_stage=%s slowest_stage_time=%.3fs",
        turn_id,
        state["language"],
        state["response_language"],
        state["path"],
        state["agent"],
        state["tool"],
        flow,
        total,
        total,
        slowest_stage,
        max(slowest_gap, 0.0),
    )
