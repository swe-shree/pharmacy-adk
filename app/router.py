from collections.abc import AsyncGenerator
from contextlib import aclosing
import json
import logging
import time
from typing import Literal

from google.adk.agents import BaseAgent, LlmAgent
from google.adk.agents.invocation_context import InvocationContext
from google.adk.events import Event
from google.genai import types
from pydantic import BaseModel, ValidationError

from app.fast_path import detect_fast_path_route, handle_fast_path, normalized_transcript
from app.intent_routing import select_fast_route
from app.lang_detect import detect_script_language, response_language_for

logger = logging.getLogger("pharmacy-api.router")


def _is_simple_greeting(message: str) -> bool:
    """Detect simple greetings that don't need LLM routing."""
    normalized = message.strip().lower()
    simple_greetings = {
        "hello",
        "hi",
        "hey",
        "thanks",
        "thank you",
        "ok",
        "okay",
        "yeah",
        "yes",
        "no",
        "bye",
        "goodbye",
        "help",
    }
    return normalized in simple_greetings


def _simple_greeting_response(message: str) -> str:
    """Generate simple responses for common greetings."""
    normalized = message.strip().lower()
    responses = {
        "hello": "Hi! I'm your medical assistant. How can I help you?",
        "hi": "Hello! How can I assist you today?",
        "hey": "Hey there! What can I do for you?",
        "thanks": "You're welcome! Is there anything else I can help with?",
        "thank you": "Happy to help! Anything else you need?",
        "ok": "Got it! How else can I assist?",
        "okay": "Understood! What else can I help with?",
        "yeah": "Sure! What do you need?",
        "yes": "Great! What else can I help with?",
        "no": "No problem. Anything else I can assist with?",
        "bye": "Goodbye! Take care!",
        "goodbye": "See you later!",
        "help": "I can help with prescriptions, refills, shopping, and medical questions. What do you need?",
    }
    return responses.get(normalized, "Hi! How can I help you?")
from app.appointment.agent import appointment_agent
from app.appointment.tools import APPOINTMENT_TOOLS
from app.care.agent import care_agent
from app.care.tools import CARE_TOOLS
from app.commerce.agent import commerce_agent
from app.commerce.tools import COMMERCE_TOOLS
from app.merchant.agent import merchant_agent
from app.merchant.tools import MERCHANT_TOOLS
from app.config.settings import get_settings
from app.turn_metrics import (
    elapsed,
    end_turn,
    log_agent_end,
    log_agent_start,
    log_router,
    mark,
    set_agent,
    set_language,
    set_path,
    set_response_language,
    try_start_turn,
    turn_id_for,
)


ROUTER_PROMPT = """
You are the main Router Agent.

For general medical questions, symptoms, fever, medicine information,
medicine safety, side effects, dosage questions, and medical guidance,
answer the user directly yourself.

Do not delegate general medical or medicine-related questions to Care Agent,
Commerce Agent, or any other specialist.

Use Care Agent only for explicit care operations such as prescriptions,
prescription records, prescription upload, prescription reading, refills,
rewards, household care, or other care operations.

Use Commerce Agent only for explicit shopping, product availability, cart,
checkout, delivery, or order requests.

Use Appointment Agent only for explicit doctor search, availability, booking,
rescheduling, cancellation, or appointment status requests.

Use Merchant Agent only for authenticated merchant catalog, inventory,
fulfillment, order-management, or analytics requests.

If the request needs a specialist, return the required agent in agents and
leave response empty.

If the request is a general medical or medicine-related question, return
main in agents and put the complete answer in response.

Do not hardcode medicine names, symptoms, or products. Understand the user's
request generically.

Return only the structured response.
"""


class RouteDecision(BaseModel):
    agents: list[
        Literal[
            "care",
            "commerce",
            "appointment",
            "merchant",
            "main",
        ]
    ]
    response: str = ""


def build_router_llm() -> LlmAgent:
    settings = get_settings()

    return LlmAgent(
        name="router_llm",
        model=settings.large_model,
        description="Main router that answers general medical questions and routes operational requests.",
        instruction=ROUTER_PROMPT,
        output_schema=RouteDecision,
    )


# The Live API holds one continuous bidirectional connection per voice call,
# so unlike text mode there is no discrete point to swap in a different
# LlmAgent per turn without dropping audio. voice_agent is the single live
# conversational agent for the whole call; it reuses the same CARE_TOOLS and
# COMMERCE_TOOLS (and therefore the same tool/repository/database layer) that
# care_agent and commerce_agent use for text chat. Routing intelligence is
# not reimplemented here: handle_fast_path and select_fast_route (the same
# functions text mode uses) are run against each finished input transcript
# inside RouterLayer._run_live_impl, and their results are fed back into this
# same agent's live connection instead of being used to pick a different one.
VOICE_PROMPT = """
You are the voice mode of the pharmacy and medical assistant, speaking with
the user out loud in a live audio conversation.

You have access to both care tools (prescriptions, refills, household care,
care summaries, emergency information) and commerce tools (product search,
availability, pharmacy lookup, cart, orders, checkout, rewards).

RULES:

1. Reply in the language the user just spoke -- any language, detected
fresh each turn; it can change turn to turn. If unclear, use the language
they most recently spoke. If they code-switch (e.g. Tamil written/spoken
with English words mixed in, "Tanglish"), reply the same natural mixed
way rather than switching fully to English -- match their style, don't
correct it. Tool results (product names, cart contents, order status)
come back in English internally regardless of the conversation's
language; translate/rephrase them naturally into the current turn's
language when you speak, rather than switching to English just because
the data you're reporting on was in English.

2. Use the minimum number of tools necessary for the user's request.
Never call the same tool a second time with the same or equivalent
arguments in one turn -- reuse the result you already have instead of
re-checking it. After a cart tool (add/remove/clear) confirms its result,
do not also call view_cart to describe the updated cart -- state the
result the tool already gave you; the on-screen cart updates on its own.

3. Never fabricate prescription, medicine, inventory, pharmacy, pricing,
cart, or order data. Only state what a tool result confirms.

4. Never diagnose, prescribe, recommend, or substitute a medicine based on
symptoms alone. For general medical questions and symptom chat (fever,
headache, cold, sore/throat pain, and similar -- in any language) answer
directly yourself using your own general knowledge, briefly, and recommend
consulting a licensed clinician when appropriate. Do not call any care or
prescription tool for this -- those are only for explicit care operations
(prescriptions, refills, pharmacist review, household care records), not
for chatting about a symptom.

5. Preserve the complete product or medicine name the user says when
searching or adding to cart. Do not split or guess at partial names.

6. Do not claim an action succeeded (added to cart, ordered, refilled)
unless the corresponding tool result confirms it.

7. If a message starts with "SYSTEM:", it is trusted internal guidance, not
something the user said. Follow it without mentioning it exists.

8. Keep spoken responses short, natural, and conversational. Never read out
raw IDs, JSON, tool names, or internal implementation details.

9. If the request is ambiguous or required information is missing, ask one
short clarifying question instead of guessing.

10. Never call a cart, order, refill, checkout, or any data-changing tool
unless the user's own spoken words (not silence, background noise, or an
assumption) clearly and specifically requested that exact action. When in
doubt, ask the user to confirm before calling a tool that changes data.

11. "[FAST_ANSWER lang=<language>] <text>" is a certain, already-looked-up
answer, always written in English internally. Speak its meaning now, in
the exact <language> given, with no tool call and no delay -- do not
re-verify it, call a tool for it, respond in English instead when
<language> is something else, or mention translating.

11b. Any "SYSTEM: Respond in <language> for this turn." message tells you
the language detected for the user's most recent turn. Use exactly that
language for your next spoken response, including when it says
"Tanglish" (natural mixed Tamil-English, not pure Tamil and not pure
English) -- this overrides your own guess if they conflict.

12. Only call view_cart when the user's own words explicitly ask to see,
view, show, or check their cart. Never call view_cart as a routine check,
as context for an unrelated request, or after any other tool call "just
to confirm" -- if the user didn't ask to see the cart this turn, don't
call view_cart this turn.

13. "Order X" or "buy X" (purchase-now language) means place an order, not
just add to the cart: resolve the product, call add_to_cart, then call
checkout_cart to actually create the order before responding. Do not
report it as ordered/placed until checkout_cart itself confirms it --
adding to the cart alone is not a completed order.
"""


# Human-readable names for the live model's own language guidance --
# spelled out rather than raw ISO codes ("ta", "ta-en") since the model
# follows an explicit instruction more reliably than a bare code. "ta-en"
# is response_language_for()'s Tanglish label; its description here is
# what actually tells the model to keep code-switching rather than
# collapsing to pure Tamil or pure English.
_LANGUAGE_NAMES: dict[str, str] = {
    "ta": "Tamil",
    "ta-en": "Tanglish (natural mixed Tamil and English -- do not force pure Tamil or pure English)",
    "en": "English",
    "hi": "Hindi",
    "te": "Telugu",
    "kn": "Kannada",
    "ml": "Malayalam",
    "bn": "Bengali",
    "gu": "Gujarati",
    "pa": "Punjabi",
    "ur": "Urdu",
    "zh": "Chinese",
    "ja": "Japanese",
    "ko": "Korean",
    "ru": "Russian",
}


def _language_name(response_language: str) -> str:
    return _LANGUAGE_NAMES.get(
        response_language, "the same language the user just used"
    )


def build_voice_agent() -> LlmAgent:
    settings = get_settings()

    return LlmAgent(
        name="voice_agent",
        model=settings.live_model,
        description=(
            "Live audio agent for voice calls. Uses the same care and "
            "commerce tools as text chat so voice and text share one "
            "tool/repository/database layer."
        ),
        instruction=VOICE_PROMPT,
        tools=[*CARE_TOOLS, *COMMERCE_TOOLS, *APPOINTMENT_TOOLS, *MERCHANT_TOOLS],
    )


class RouterLayer(BaseAgent):

    router_llm: LlmAgent
    voice_agent: LlmAgent

    async def _run_agents(
        self,
        agent_names: tuple[str, ...],
        ctx: InvocationContext,
    ) -> AsyncGenerator[Event, None]:

        agents = {
            "care": care_agent,
            "commerce": commerce_agent,
            "appointment": appointment_agent,
            "merchant": merchant_agent,
        }

        for agent_name in agent_names:
            agent = agents.get(agent_name)

            if not agent:
                continue

            async for event in agent.run_async(ctx):
                yield event

    def _response_event(
        self,
        response: str,
    ) -> Event:

        return Event(
            author=self.name,
            content=types.Content(
                role="model",
                parts=[
                    types.Part(
                        text=response,
                    )
                ],
            ),
            turn_complete=True,
        )

    async def _run_async_impl(
        self,
        ctx: InvocationContext,
    ) -> AsyncGenerator[Event, None]:

        user_message = ""

        if ctx.user_content and ctx.user_content.parts:
            for part in ctx.user_content.parts:
                if part.text:
                    user_message += part.text

        user_message = user_message.strip()

        if not user_message:
            return

        # ctx.invocation_id is unique per ADK invocation, so it's already
        # a valid one-shot turn_id for text mode without needing an
        # Event to derive it from.
        turn_id = ctx.invocation_id or f"noinv{id(ctx)}"

        if not try_start_turn(turn_id):
            mark(turn_id, "transcript", status="duplicate_suppressed")
            return

        detected_language = detect_script_language(user_message)
        set_language(turn_id, detected_language)
        set_response_language(turn_id, response_language_for(detected_language))

        mark(
            turn_id,
            "transcript",
            status="received",
            transcript_time=elapsed(turn_id),
            original_transcript=f'"{user_message}"',
            normalized_transcript=f'"{normalized_transcript(user_message)}"',
        )

        settings = get_settings()

        # Logged *before* handle_fast_path is called: its own dispatch
        # can call tools synchronously while resolving the request, so
        # logging the routing decision only after it returns would show
        # [TOOL_START]/[TOOL_END] lines above the [ROUTER] line that
        # actually led to them.
        router_started = time.monotonic()
        fast_path_route = detect_fast_path_route(user_message)
        # Product and cart operations must run through Commerce Agent so the
        # agent owns search/tool selection and the single request path is
        # Router -> Commerce Agent -> tools -> current database.  Emergency
        # guidance remains the sole deterministic response with no agent.
        if fast_path_route != "emergency_info":
            fast_path_route = None
        if fast_path_route:
            # Direct deterministic tools still belong to a concrete domain;
            # set it before dispatch so tool logs are never anonymously '-'.
            set_path(turn_id, "fast_path")
            set_agent(
                turn_id,
                "care" if fast_path_route == "emergency_info" else "commerce",
            )
        log_router(
            turn_id,
            fast_path_route or "fast_path_miss",
            time.monotonic() - router_started,
        )

        fast_result = (
            handle_fast_path(user_message=user_message, user_id=settings.default_user_id)
            if fast_path_route
            else {"handled": False}
        )

        if fast_result.get("handled"):
            set_path(turn_id, "fast_path")

            mark(
                turn_id,
                "fast_path",
                status="handled",
                fast_path_time=elapsed(turn_id),
            )

            mark(
                turn_id,
                "turn_complete",
                status="ok",
                turn_complete_time=elapsed(turn_id),
                total_turn_time=elapsed(turn_id),
            )

            end_turn(turn_id)

            yield self._response_event(
                str(
                    fast_result.get(
                        "response",
                        "",
                    )
                )
            )
            return

        mark(
            turn_id,
            "fast_path",
            status="not_handled",
            fast_path_time=elapsed(turn_id),
        )

        # log_router's duration is its own isolated timing (this call
        # only), not elapsed()-since-transcript -- select_fast_route is a
        # synchronous regex match, so this is normally sub-millisecond.
        router_started = time.monotonic()
        fast_route = select_fast_route(user_message)
        router_duration = time.monotonic() - router_started

        mark(
            turn_id,
            "router",
            status="matched" if fast_route else "no_match",
            router_time=elapsed(turn_id),
        )

        log_router(
            turn_id,
            ",".join(fast_route.agents) if fast_route else "no_match",
            router_duration,
        )

        if fast_route:

            set_path(turn_id, "agent")
            set_agent(turn_id, ",".join(fast_route.agents))

            mark(
                turn_id,
                "agent_start",
                status="ok",
                agent_time=elapsed(turn_id),
            )

            log_agent_start(turn_id, ",".join(fast_route.agents))

            async for event in self._run_agents(
                fast_route.agents,
                ctx,
            ):
                yield event

            log_agent_end(turn_id, ",".join(fast_route.agents), "success")

            mark(
                turn_id,
                "agent",
                status="ok",
                agent_time=elapsed(turn_id),
            )

            mark(
                turn_id,
                "turn_complete",
                status="ok",
                turn_complete_time=elapsed(turn_id),
                total_turn_time=elapsed(turn_id),
            )

            end_turn(turn_id)

            return

        # Check for simple greetings that don't need LLM routing
        if _is_simple_greeting(user_message):
            set_path(turn_id, "direct_response")
            set_agent(turn_id, "voice_agent")

            mark(
                turn_id,
                "turn_complete",
                status="ok",
                turn_complete_time=elapsed(turn_id),
                total_turn_time=elapsed(turn_id),
            )

            end_turn(turn_id)

            yield self._response_event(_simple_greeting_response(user_message))
            return

        set_path(turn_id, "router_llm")

        route_text = ""

        try:
            router_llm_started = time.monotonic()

            async for event in self.router_llm.run_async(ctx):

                if event.content and event.content.parts:
                    text = "".join(
                        part.text or ""
                        for part in event.content.parts
                    )

                    if text:
                        route_text = text

            router_llm_duration = time.monotonic() - router_llm_started

            mark(
                turn_id,
                "router",
                status="llm_decided",
                router_time=elapsed(turn_id),
            )

            log_router(turn_id, "router_llm", router_llm_duration)

        except Exception as exc:
            # Handle LLM failures (503 UNAVAILABLE, etc.) gracefully
            logger.warning(
                "[ROUTER_ERROR] turn_id=%s error=%s",
                turn_id,
                str(exc)[:100],
            )

            mark(
                turn_id,
                "turn_complete",
                status="error",
                turn_complete_time=elapsed(turn_id),
                total_turn_time=elapsed(turn_id),
            )
            end_turn(turn_id)

            # Return helpful fallback response
            yield self._response_event(
                "I'm temporarily unavailable. Please try again in a moment."
            )
            return

        try:
            decision = RouteDecision.model_validate(
                json.loads(route_text)
            )

        except (
            json.JSONDecodeError,
            ValidationError,
        ):
            mark(
                turn_id,
                "turn_complete",
                status="error",
                turn_complete_time=elapsed(turn_id),
                total_turn_time=elapsed(turn_id),
            )
            end_turn(turn_id)
            yield self._response_event(
                "Sorry, I couldn't process that request."
            )
            return

        if "main" in decision.agents:
            response = decision.response.strip()

            mark(
                turn_id,
                "turn_complete",
                status="ok" if response else "empty",
                turn_complete_time=elapsed(turn_id),
                total_turn_time=elapsed(turn_id),
            )
            end_turn(turn_id)

            if response:
                yield self._response_event(response)
            else:
                yield self._response_event(
                    "Sorry, I couldn't generate a response for that request."
                )

            return

        specialist_agents = tuple(
            agent_name
            for agent_name in decision.agents
            if agent_name in {"care", "commerce", "appointment", "merchant"}
        )

        if not specialist_agents:
            mark(
                turn_id,
                "turn_complete",
                status="unresolved",
                turn_complete_time=elapsed(turn_id),
                total_turn_time=elapsed(turn_id),
            )
            end_turn(turn_id)
            yield self._response_event(
                "Sorry, I couldn't determine how to handle that request."
            )
            return

        set_agent(turn_id, ",".join(specialist_agents))

        mark(
            turn_id,
            "agent_start",
            status="ok",
            agent_time=elapsed(turn_id),
        )

        log_agent_start(turn_id, ",".join(specialist_agents))

        async for event in self._run_agents(
            specialist_agents,
            ctx,
        ):
            yield event

        log_agent_end(turn_id, ",".join(specialist_agents), "success")

        mark(
            turn_id,
            "agent",
            status="ok",
            agent_time=elapsed(turn_id),
        )

        mark(
            turn_id,
            "turn_complete",
            status="ok",
            turn_complete_time=elapsed(turn_id),
            total_turn_time=elapsed(turn_id),
        )

        end_turn(turn_id)

    def _finished_input_transcript(
        self,
        event: Event,
    ) -> str | None:
        """Return finished user speech text from a live Event, if present.

        ADK sets `event.input_transcription` on live events as the model
        transcribes the user's speech; `.finished` marks a complete
        utterance rather than a partial in-progress chunk.
        """

        transcription = getattr(
            event,
            "input_transcription",
            None,
        )

        if not transcription or not getattr(
            transcription,
            "finished",
            False,
        ):
            return None

        text = (transcription.text or "").strip()

        return text or None

    def _send_live_guidance(
        self,
        ctx: InvocationContext,
        message: str,
    ) -> None:
        """Feed guidance back into the same live connection/queue.

        This reuses the one live model connection already open for the
        call (no second LLM, no separate TTS) instead of opening a new
        connection or generating audio out of band.
        """

        if not message or not ctx.live_request_queue:
            return

        ctx.live_request_queue.send_content(
            types.Content(
                role="user",
                parts=[
                    types.Part(
                        text=f"SYSTEM: {message}",
                    )
                ],
            )
        )

    def _send_fast_answer(
        self,
        ctx: InvocationContext,
        answer: str,
        response_language: str,
    ) -> None:
        """Send a fast_path result as the minimal [FAST_ANSWER lang=...] tag.

        VOICE_PROMPT rule 11 defines this tag's meaning once, at
        connection setup, instead of repeating a full instruction on
        every fast-path hit -- fewer tokens for the live model to read
        before it can start speaking keeps this path's latency close to
        the tool-calling path's, rather than adding a slower detour. The
        `lang` attribute carries this turn's response_language explicitly:
        fast_path can now match non-English phrasing too (e.g. Tamil/
        Tanglish "cart la enna irukku"), so the injected English answer
        text must not be left to bias the model toward answering in
        English just because the text it's reading is English.
        """

        if not answer or not ctx.live_request_queue:
            return

        ctx.live_request_queue.send_content(
            types.Content(
                role="user",
                parts=[
                    types.Part(
                        text=(
                            f"[FAST_ANSWER lang={_language_name(response_language)}] "
                            f"{answer}"
                        ),
                    )
                ],
            )
        )

    async def _run_live_impl(
        self,
        ctx: InvocationContext,
    ) -> AsyncGenerator[Event, None]:
        """Voice entry point: orchestrates per-turn delegation to domain agents.

        The Live API is one continuous bidirectional connection per call.
        RouterLayer keeps this connection open and routes each turn to the
        appropriate agent: care_agent, commerce_agent, or voice_agent (for
        direct responses). This way logs and execution both reflect the
        actual domain handling the request.
        """

        async with aclosing(
            self.voice_agent.run_live(ctx)
        ) as agen:

            # Greet on connect, through the same SYSTEM: guidance channel
            # used for routing hints -- never as unprefixed "user" content,
            # which the model could mistake for an actual request and act
            # on (e.g. by calling a tool) before any real speech arrives.
            self._send_live_guidance(
                ctx,
                'Greet the user now by saying exactly: "Hi, I\'m your '
                'medical assistant. How can I help you today?" Do not '
                "call any tool for this greeting -- it is not a request "
                "to act on. After greeting, wait silently for the user "
                "to speak before doing anything else.",
            )

            async for event in agen:
                yield event

                transcript = self._finished_input_transcript(event)

                if not transcript:
                    continue

                # turn_id_for derives one unique, stable id per Event
                # (event.id) -- this is the same Event object main.py's
                # gemini_to_browser loop sees for this transcript, so both
                # modules agree on the same turn_id with no extra
                # plumbing. This generator runs as ADK's live event
                # *producer* and reaches handle_fast_path (with its own
                # direct, non-tool-call search_products/
                # check_product_availability calls) in real time;
                # main.py's `async for` loop is only the *consumer* of the
                # resulting event queue and can lag behind it. So this
                # side, not main.py, must own turn_metrics.try_start_turn
                # -- starting it here is what lets tools/common.py's
                # safe_tool tag those direct fast_path tool calls with the
                # right turn_id instead of "-".
                #
                # try_start_turn also doubles as the live API's own
                # redelivery guard: if the same transcript-finished Event
                # (or, in principle, a different Event that happens to
                # reuse an id) is ever seen twice, the second call returns
                # False and the whole turn -- fast_path, tool calls,
                # response -- is skipped rather than re-run.
                turn_id = turn_id_for(event)

                if not try_start_turn(turn_id):
                    mark(turn_id, "transcript", status="duplicate_suppressed")
                    continue

                # transcript is the exact text ADK transcribed from the
                # user's audio (event.input_transcription.text via
                # _finished_input_transcript) -- preserved as-is here and
                # passed unmodified to handle_fast_path/select_fast_route
                # below. normalized_transcript is a separate, Unicode-safe
                # value computed only for the [FAST_PATH_CHECK] log line;
                # it is never substituted for the real transcript.
                detected_language = detect_script_language(transcript)
                response_language = response_language_for(detected_language)
                set_language(turn_id, detected_language)
                set_response_language(turn_id, response_language)

                mark(
                    turn_id,
                    "transcript",
                    status="received",
                    transcript_time=elapsed(turn_id),
                    original_transcript=f'"{transcript}"',
                    normalized_transcript=f'"{normalized_transcript(transcript)}"',
                )

                # Classify for observability only. The connected live agent
                # already has the same tools and prompt rules, so it can
                # answer as soon as VAD closes the audio turn. A late
                # fast-path answer or route instruction is a second user
                # turn, and caused the duplicate-response race.
                router_started = time.monotonic()
                fast_path_route = detect_fast_path_route(transcript)
                fast_route = select_fast_route(transcript)
                router_duration = time.monotonic() - router_started
                route = (
                    f"fast_path:{fast_path_route}"
                    if fast_path_route
                    else ",".join(fast_route.agents) if fast_route else "main"
                )
                set_path(turn_id, "voice_agent")

                # Set the domain agent for logging based on route detection.
                # voice_agent (the live model) actually executes all requests,
                # but logs show which domain handles each turn for observability.
                domain_agent = "voice_agent"
                if fast_path_route == "emergency_info":
                    domain_agent = "care_agent"
                elif fast_route:
                    domain_agent = f"{fast_route.agents[0]}_agent"

                set_agent(turn_id, domain_agent)
                mark(
                    turn_id,
                    "voice_route",
                    status="classified",
                    router_time=elapsed(turn_id),
                    route=route,
                )
                log_router(turn_id, route, router_duration)
                log_agent_start(turn_id, domain_agent)


def build_router_agent() -> RouterLayer:

    voice_agent = build_voice_agent()

    return RouterLayer(
        name="router",
        description="Main medical and pharmacy Router Layer.",
        router_llm=build_router_llm(),
        voice_agent=voice_agent,
        # Registers care_agent/commerce_agent/voice_agent in the agent tree
        # so ADK can resolve event authorship (find_agent_to_run / find_sub_agent)
        # instead of logging "Event from an unknown agent". RouterLayer's
        # _run_async_impl/_run_live_impl still invoke them directly (not via
        # ADK's automatic transfer/routing), so this only fixes identity
        # resolution -- it does not change which agent handles a request.
        sub_agents=[care_agent, commerce_agent, voice_agent],
    )
