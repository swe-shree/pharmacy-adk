import asyncio
import json
import logging
import sys
import time
import uuid

from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware
from google.adk.agents.live_request_queue import LiveRequestQueue
from google.adk.agents.run_config import RunConfig, StreamingMode
from google.adk.runners import Runner
from google.adk.sessions import InMemorySessionService
from google.genai import types

from app.agent import root_agent
from app.commerce.tools import check_product_availability, view_cart
from app.config.settings import get_settings
from app.database import database as DB
from app.turn_metrics import (
    elapsed,
    end_turn,
    get_agent,
    get_path,
    get_tool,
    is_completed,
    log_agent_end,
    log_agent_flow,
    log_first_audio,
    mark,
    mark_first_audio_sent,
    set_tool,
    set_agent,
    set_path,
    try_start_turn,
    turn_id_for,
)
from app.voice.session import VoiceSession


# On Windows, a redirected/non-console stdout or stderr stream can fall
# back to the system ANSI codepage instead of UTF-8, silently replacing
# Tamil (and any other non-Latin) log text with "?" -- this makes
# original_transcript/response log lines unreadable without touching any
# actual request/response data (that already flows as proper UTF-8
# through FastAPI/ADK). Force both streams to UTF-8 before logging is
# configured so log output matches what's really being processed.
for _stream in (sys.stdout, sys.stderr):
    if hasattr(_stream, "reconfigure"):
        _stream.reconfigure(encoding="utf-8", errors="replace")

import os

log_dir = "logs"
if not os.path.exists(log_dir):
    os.makedirs(log_dir)

log_format = "%(asctime)s | %(levelname)s | %(name)s | %(message)s"
logging.basicConfig(
    level=logging.INFO,
    format=log_format,
)

# Add file handler for persistent logging
file_handler = logging.FileHandler(os.path.join(log_dir, "server.log"))
file_handler.setLevel(logging.INFO)
file_handler.setFormatter(logging.Formatter(log_format))

# Add to root logger so all loggers inherit it
logging.getLogger().addHandler(file_handler)

logger = logging.getLogger("pharmacy-api")


app = FastAPI(
    title=" Personal AI API",
    version="1.0.0",
)


app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        "http://127.0.0.1:3000",
        "http://localhost:3000",
    ],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.middleware("http")
async def track_http_turn(request, call_next):
    """Give non-chat API calls the same trace identity as ADK turns."""
    turn_id = f"http-{uuid.uuid4().hex}"
    try_start_turn(turn_id)
    set_path(turn_id, "api")
    if request.url.path in {"/cart", "/products"}:
        set_agent(turn_id, "commerce_api")
    try:
        response = await call_next(request)
        return response
    finally:
        end_turn(turn_id)


session_service = InMemorySessionService()


runner = Runner(
    app_name="pharmacy",
    agent=root_agent,
    session_service=session_service,
)


created_sessions: set[tuple[str, str]] = set()


async def ensure_session(
    user_id: str,
    session_id: str,
) -> None:

    key = (
        user_id,
        session_id,
    )

    if key in created_sessions:
        return

    await session_service.create_session(
        app_name="pharmacy",
        user_id=user_id,
        session_id=session_id,
    )

    created_sessions.add(key)


@app.get("/")
async def root():
    return {
        "message":
            "Pharmacy Personal AI API is running",
    }


@app.get("/health")
async def health():
    return {
        "status": "ok",
        "service": "pharamacy-api",
    }


@app.get("/cart")
async def cart(user_id: str = "user_001"):
    """Thin REST wrapper around the existing view_cart tool.

    Chat and voice both mutate the cart through app.commerce.tools directly
    against the shared database; this endpoint reads that same tool/DB so the
    frontend can refresh its cart badge without going through the LLM.
    """

    result = view_cart(user_id=user_id)

    if not result.get("success"):
        return {
            "success": False,
            "error": result.get("error", {}).get(
                "message", "Could not load cart"
            ),
        }

    data = result.get("data") or {}
    items = data.get("items", [])

    return {
        "success": True,
        "item_count": sum(
            item.get("quantity", 0) for item in items
        ),
        "items": items,
    }


@app.get("/products")
async def products():
    """Read-only listing of the current catalog for the frontend product grid.

    Thin wrapper, same pattern as /cart above: reuses the existing
    check_product_availability tool and the same database the chat/voice
    tools already read from, so the catalog and stock counts the frontend
    shows always match what fast_path/agents would report -- no separate
    or duplicated product/inventory logic.
    """

    catalog = []

    for product in DB["products"]:

        availability = check_product_availability(
            product_id=product["id"]
        )

        stock = 0

        if availability.get("success"):
            stock = sum(
                entry.get("quantity", 0)
                for entry in (
                    availability.get("data") or {}
                ).get("availability", [])
            )

        catalog.append({
            "id": product["id"],
            "name": product["name"],
            "generic_name": product.get("generic_name"),
            "category": product.get("category"),
            "price": product.get("price"),
            "requires_prescription": product.get(
                "requires_prescription", False
            ),
            "stock": stock,
            "in_stock": stock > 0,
            "image_url": product.get("image_url"),
        })

    return {
        "success": True,
        "products": catalog,
    }


@app.post("/chat")
async def chat(request: dict):

    user_id = str(
        request.get(
            "user_id",
            "user_001",
        )
    )

    message = str(
        request.get(
            "message",
            "",
        )
    ).strip()

    session_id = str(
        request.get(
            "session_id",
            user_id,
        )
    )

    if not message:
        return {
            "success": False,
            "error":
                "Message cannot be empty",
        }

    logger.info(
        "[CHAT_REQUEST] user=%s message=%s",
        user_id,
        message,
    )

    try:

        await ensure_session(
            user_id,
            session_id,
        )

        content = types.Content(
            role="user",
            parts=[
                types.Part(
                    text=message
                )
            ],
        )

        response_parts: list[str] = []

        async for event in runner.run_async(
            user_id=user_id,
            session_id=session_id,
            new_message=content,
        ):

            if (
                not event.content
                or not event.content.parts
            ):
                continue

            for part in event.content.parts:

                text = getattr(
                    part,
                    "text",
                    None,
                )

                if text:
                    response_parts.append(
                        text
                    )

        response_text = "".join(
            response_parts
        ).strip()

        logger.info(
        "[CHAT_RESPONSE] user=%s response=%r",
            user_id,
            response_text,
        )

        if not response_text:
            return {
                "success": False,
                "user_id": user_id,
                "session_id": session_id,
                "error":
                    "The agent returned an empty response.",
            }

        return {
            "success": True,
            "user_id": user_id,
            "session_id": session_id,
            "response": response_text,
        }

    except Exception as exc:

        logger.exception(
            "[CHAT_ERROR]"
        )

        return {
            "success": False,
            "user_id": user_id,
            "session_id": session_id,
            "error": str(exc),
        }


@app.websocket("/voice/ws")
async def voice_websocket(
    websocket: WebSocket,
):

    settings = get_settings()

    user_id = str(
        websocket.query_params.get("user_id")
        or settings.default_user_id
    )

    session_id = str(
        websocket.query_params.get("session_id")
        or user_id
    )

    await websocket.accept()

    connection_id = str(
        uuid.uuid4()
    )

    connected_at = time.monotonic()

    logger.info(
        "[VOICE_CONNECTED] %s user=%s session=%s",
        connection_id,
        user_id,
        session_id,
    )

    # Voice shares the same ADK session (and therefore the same
    # conversation history / user scoping) as the text /chat endpoint.
    await ensure_session(
        user_id,
        session_id,
    )

    live_request_queue = LiveRequestQueue()

    voice_session = VoiceSession(
        session_id=session_id,
        user_id=user_id,
        live_session=live_request_queue,
    )

    run_config = RunConfig(
        streaming_mode=StreamingMode.BIDI,
        response_modalities=["AUDIO"],
    )

    try:

        await websocket.send_json({
            "type": "connected",
            "connection_id":
                connection_id,
        })

        async def browser_to_gemini():

            try:

                while True:

                    message = (
                        await websocket.receive()
                    )

                    if message.get("type") == (
                        "websocket.disconnect"
                    ):
                        raise WebSocketDisconnect(
                            message.get("code", 1000)
                        )

                    audio_data = message.get(
                        "bytes"
                    )

                    if audio_data:

                        live_request_queue.send_realtime(
                            types.Blob(
                                data=audio_data,
                                mime_type=
                                    "audio/pcm;rate=16000",
                            )
                        )

                        continue

                    text_data = message.get(
                        "text"
                    )

                    if not text_data:
                        continue

                    try:

                        payload = json.loads(
                            text_data
                        )

                    except json.JSONDecodeError:

                        payload = {
                            "type": "text",
                            "text": text_data,
                        }

                    if payload.get(
                        "type"
                    ) == "text":

                        text = str(
                            payload.get(
                                "text",
                                "",
                            )
                        ).strip()

                        if text:

                            live_request_queue.send_content(
                                types.Content(
                                    role="user",
                                    parts=[
                                        types.Part(
                                            text=text
                                        )
                                    ],
                                )
                            )

            except WebSocketDisconnect:
                raise

            finally:
                live_request_queue.close()


        async def gemini_to_browser():

            # Output transcription arrives as incremental chunks that
            # reset on `finished`; accumulate so the frontend gets one
            # clean line per spoken turn instead of many tiny bubbles.
            output_transcript_buffer = ""

            # The live API can emit several `turn_complete` (and, rarely,
            # repeated transcript/text) events back to back for one
            # logical assistant turn. Track what's already been forwarded
            # for the current turn so repeats are dropped instead of
            # re-sent to the frontend.
            assistant_activity_since_turn_complete = False
            last_sent_user_transcript = None
            last_sent_assistant_transcript = None

            # Set when the user's speech finishes; cleared the moment the
            # first byte of the response comes back, so we can measure and
            # log time-to-first-audio for that turn exactly once.
            awaiting_first_audio_since = None

            # turn_id_for(event) mirrors router.py's derivation exactly
            # (both read the same Event.id) so both log streams -- and,
            # via turn_metrics, the same timing/completion state -- line
            # up with no extra plumbing between the two modules.
            # router.py's live loop is the actual event *producer* and
            # owns turn_metrics.try_start_turn for each turn_id (it runs
            # handle_fast_path, with its own direct tool calls, in real
            # time); this loop is only the *consumer* of the resulting
            # event queue and can lag behind it, so it reuses that state
            # rather than starting its own. "-" is the sentinel for "no
            # real turn yet" (e.g. the connect-time greeting, which has
            # no transcript/turn_id of its own) and is never subject to
            # the is_completed gate below.
            current_turn_id = "-"

            # Function-call/response ids seen for the current turn, so a
            # redelivered part (the live API can repeat identical parts
            # across streamed events) is not logged as a second tool
            # dispatch. The actual tool *execution* can't double-count
            # regardless -- app/tools/common.py only logs when the Python
            # function body itself runs -- but this keeps the dispatch-
            # level log line honest too.
            seen_call_ids: set[str] = set()
            seen_response_ids: set[str] = set()

            async for event in (
                runner.run_live(
                    user_id=user_id,
                    session_id=session_id,
                    live_request_queue=live_request_queue,
                    run_config=run_config,
                )
            ):

                input_transcription = (
                    event.input_transcription
                )

                if (
                    input_transcription
                    and input_transcription.finished
                    and input_transcription.text
                    and input_transcription.text
                    != last_sent_user_transcript
                ):

                    new_turn_id = turn_id_for(event)

                    if is_completed(new_turn_id):

                        # A duplicate/late delivery of a transcript event
                        # whose turn already sent its one response. Do
                        # not touch current_turn_id or forward anything
                        # for it -- everything that follows in this loop
                        # iteration stays scoped to whatever turn was
                        # already active.
                        mark(
                            new_turn_id,
                            "transcript",
                            status="duplicate_suppressed",
                        )

                    else:

                        current_turn_id = new_turn_id

                        last_sent_user_transcript = (
                            input_transcription.text
                        )

                        last_sent_assistant_transcript = None
                        seen_call_ids = set()
                        seen_response_ids = set()

                        # router.py's live loop is the actual event
                        # *producer* for this turn_id and already called
                        # turn_metrics.try_start_turn for it (it reaches
                        # handle_fast_path, in real time, before this
                        # *consumer* loop necessarily gets to this event)
                        # -- this just reuses that same timing state.
                        mark(
                            current_turn_id,
                            "transcript_seen",
                            status="ok",
                            transcript_time=elapsed(current_turn_id),
                        )

                        await websocket.send_json({
                            "type":
                                "user_transcript",
                            "text":
                                input_transcription.text,
                        })

                        awaiting_first_audio_since = (
                            time.monotonic()
                        )

                if current_turn_id != "-" and is_completed(current_turn_id):

                    # A late ADK event (trailing audio, a stray tool call,
                    # etc.) for a turn that already sent its one response.
                    # Ignored entirely -- not forwarded to the frontend,
                    # not treated as new activity.
                    mark(
                        current_turn_id,
                        "event",
                        status="duplicate_suppressed",
                    )
                    continue

                if (
                    event.content
                    and event.content.parts
                ):

                    for part in (
                        event.content.parts
                    ):

                        if part.function_call:

                            call_id = (
                                part.function_call.id
                                or part.function_call.name
                            )

                            if call_id not in seen_call_ids:
                                seen_call_ids.add(call_id)

                                # The live API can start generating a tool
                                # call from raw audio before our fast_path
                                # guidance reaches the model -- if that
                                # happens, the turn's path is already
                                # "fast_path" by the time this call
                                # surfaces, so flag it instead of quietly
                                # mislabeling it a normal agent call.
                                already_fast_pathed = (
                                    get_path(current_turn_id) == "fast_path"
                                )

                                set_tool(current_turn_id, part.function_call.name)

                                mark(
                                    current_turn_id,
                                    "tool_dispatch",
                                    status=(
                                        "redundant_after_fast_path"
                                        if already_fast_pathed
                                        else "called"
                                    ),
                                )

                        if part.function_response:

                            response_id = (
                                part.function_response.id
                                or part.function_response.name
                            )

                            if response_id not in seen_response_ids:
                                seen_response_ids.add(response_id)

                                set_tool(current_turn_id, part.function_response.name)

                                mark(
                                    current_turn_id,
                                    "tool_result",
                                    status="ok",
                                )

                        if (
                            part.inline_data
                            and
                            part.inline_data.data
                        ):

                            if awaiting_first_audio_since is not None:

                                mark(
                                    current_turn_id,
                                    "first_audio",
                                    status="ok",
                                    first_audio_time=elapsed(current_turn_id),
                                )

                                log_first_audio(
                                    current_turn_id,
                                    elapsed(current_turn_id),
                                )

                                mark_first_audio_sent(current_turn_id)

                                awaiting_first_audio_since = None

                            await websocket.send_bytes(
                                part.inline_data.data
                            )

                            assistant_activity_since_turn_complete = (
                                True
                            )

                        if part.text:

                            await websocket.send_json({
                                "type":
                                    "assistant_text",
                                "text":
                                    part.text,
                            })

                            assistant_activity_since_turn_complete = (
                                True
                            )


                output_transcription = (
                    event.output_transcription
                )

                if output_transcription:

                    if output_transcription.text:

                        # Each chunk carries the cumulative transcript so
                        # far (not just a delta), so overwrite rather than
                        # append -- appending double-concatenates it.
                        output_transcript_buffer = (
                            output_transcription.text
                        )

                    if output_transcription.finished:

                        final_text = (
                            output_transcript_buffer.strip()
                        )

                        output_transcript_buffer = ""

                        if (
                            final_text
                            and final_text
                            != last_sent_assistant_transcript
                        ):

                            last_sent_assistant_transcript = (
                                final_text
                            )

                            await websocket.send_json({
                                "type":
                                    "assistant_transcript",
                                "text": final_text,
                            })

                            assistant_activity_since_turn_complete = (
                                True
                            )


                if event.turn_complete:

                    if assistant_activity_since_turn_complete:

                        # Voice is one continuous live connection, so
                        # there's no synchronous "the agent call just
                        # returned" point the way text mode has --
                        # log_agent_start (router.py) recorded a real
                        # start timestamp when this turn picked an agent
                        # domain; this is the first point an isolated
                        # end-to-end duration for that agent's work is
                        # actually knowable, at the turn's real completion.
                        if (
                            current_turn_id != "-"
                            and get_path(current_turn_id) == "agent"
                        ):
                            log_agent_end(
                                current_turn_id,
                                get_agent(current_turn_id),
                                "success",
                            )

                        mark(
                            current_turn_id,
                            "turn_complete",
                            status="ok",
                            turn_complete_time=elapsed(current_turn_id),
                            total_turn_time=elapsed(current_turn_id),
                        )

                        await websocket.send_json({
                            "type":
                                "turn_complete",
                        })

                        # Log complete agent flow for this turn
                        if current_turn_id != "-":
                            tool_name = get_tool(current_turn_id)
                            log_agent_flow(
                                current_turn_id,
                                last_sent_user_transcript or "unknown",
                                tool_name,
                            )

                        # One clean summary line for the direct-response
                        # path only: voice_agent answered from its own
                        # knowledge (e.g. "I have fever") without
                        # dispatching any care/commerce/appointment/
                        # merchant tool this turn -- get_tool(...) == "-"
                        # is exactly that signal (set_tool is only ever
                        # called from a real tool_dispatch/tool_result
                        # event above). Delegated requests that did call a
                        # tool don't get this line, so it never claims
                        # "direct_response" for a Commerce/Care/etc. turn.
                        if (
                            current_turn_id != "-"
                            and get_path(current_turn_id) == "voice_agent"
                            and get_agent(current_turn_id) == "voice_agent"
                            and get_tool(current_turn_id) == "-"
                        ):
                            logger.info(
                                '[VOICE_FLOW] USER="%s" → ROUTER → '
                                "direct_response → AUDIO_RESPONSE → "
                                "COMPLETE",
                                last_sent_user_transcript,
                            )

                        assistant_activity_since_turn_complete = (
                            False
                        )

                        # Marks this turn_id completed for good: the
                        # is_completed gate above now refuses any further
                        # event (a late tool call, trailing audio, a
                        # repeated turn_complete) still carrying this
                        # turn_id, and tools/common.py's safe_tool refuses
                        # to execute any tool call still tagged with it.
                        if current_turn_id != "-":
                            end_turn(current_turn_id)

                    else:

                        # Same turn_id, no new activity since the last
                        # turn_complete (or none yet) -- a duplicate
                        # completion signal for a turn that hasn't
                        # produced its one response yet.
                        mark(
                            current_turn_id,
                            "turn_complete",
                            status="duplicate_suppressed",
                        )


        # NOT asyncio.gather: when browser_to_gemini() raises
        # WebSocketDisconnect, gather propagates that exception but does
        # NOT cancel gemini_to_browser(), which keeps running in the
        # background indefinitely -- still consuming Gemini Live events
        # for a closed connection, still calling turn_metrics.mark() with
        # whatever turn_id happened to be current, and never getting
        # cleaned up. That orphaned task is what produced turn_complete
        # log lines with implausibly large durations (90s, 147s...)
        # attributed to unrelated later connections. asyncio.wait +
        # explicit cancellation of whichever task didn't finish first
        # closes that leak while keeping the exact same two coroutines
        # and the same run_live usage.
        tasks = [
            asyncio.create_task(browser_to_gemini()),
            asyncio.create_task(gemini_to_browser()),
        ]

        try:
            done, pending = await asyncio.wait(
                tasks,
                return_when=asyncio.FIRST_COMPLETED,
            )

            for task in pending:
                task.cancel()

            for task in pending:
                try:
                    await task
                except (asyncio.CancelledError, Exception):
                    pass

            for task in done:
                task.result()

        finally:
            for task in tasks:
                if not task.done():
                    task.cancel()


    except WebSocketDisconnect:

        logger.info(
            "[VOICE_DISCONNECTED] %s (%.3fs)",
            connection_id,
            time.monotonic() - connected_at,
        )


    except Exception as exc:

        logger.exception(
            "[VOICE_ERROR] %s",
            connection_id,
        )

        try:

            await websocket.send_json({
                "type": "error",
                "message": str(exc),
            })

        except Exception:
            pass

    finally:

        live_request_queue.close()

        voice_session.active = False
