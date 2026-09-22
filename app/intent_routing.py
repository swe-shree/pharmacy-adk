"""Low-latency selection for explicit operational requests.

General medicine questions, symptoms, and medical guidance are handled by the
main router, not a specialist. This module delegates only explicit prescription
operations and commerce actions.
"""

from dataclasses import dataclass
import re


@dataclass(frozen=True)
class FastRoute:
    agents: tuple[str, ...]


# These are domain/action indicators, rather than a vocabulary of catalog items
# or medical conditions.  They let clearly stated requests skip the router LLM.
_COMMERCE_CONTEXT = re.compile(
    r"\b(?:cart|basket|checkout|order|delivery|shipment|availability|"
    r"in[ -]?stock|out[ -]?of[ -]?stock|inventory|pharmacy|price|cost)\b",
    re.IGNORECASE,
)
_COMMERCE_ACTION = re.compile(
    r"\b(?:buy|purchase|shop|add|remove|delete|clear|empty|search|find|"
    r"locate|track|reorder|cancel|return)\b",
    re.IGNORECASE,
)
_CARE_OPERATION = re.compile(
    r"\b(?:prescription|rx|refill)\b",
    re.IGNORECASE,
)
_GENERAL_MEDICINE_CONTEXT = re.compile(
    r"\b(?:medical|health|healthcare|symptoms?|dosage|dose|"
    r"side[ -]?effects?|interaction|contraindication|diagnos(?:is|e)|treatment|"
    r"medicine\s+(?:information|guidance|safety)|medication\s+(?:information|guidance|safety))\b",
    re.IGNORECASE,
)
_OTHER_SPECIALIST_CONTEXT = re.compile(
    r"\b(?:appointment|booking|reschedule|physician|merchant|seller|"
    r"fulfillment|analytics)\b",
    re.IGNORECASE,
)
def select_fast_route(message: str) -> FastRoute | None:
    """Return a direct agent route only when intent is unambiguous."""
    text = message.strip()
    if not text:
        return None
    if _OTHER_SPECIALIST_CONTEXT.search(text):
        return None

    # Never let a broad commerce verb (for example, "find") send a general
    # medicine-information request away from the main router.
    if _GENERAL_MEDICINE_CONTEXT.search(text) and not _CARE_OPERATION.search(text):
        return None

    has_commerce = bool(_COMMERCE_CONTEXT.search(text)) or bool(
        _COMMERCE_ACTION.search(text)
    )
    has_care = bool(_CARE_OPERATION.search(text))

    if has_commerce and has_care:
        return FastRoute(("care", "commerce"))
    if has_commerce:
        return FastRoute(("commerce",))
    if has_care:
        return FastRoute(("care",))
    return None
