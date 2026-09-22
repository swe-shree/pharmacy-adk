import logging
import re

from app.commerce.tools import (
    add_to_cart,
    check_product_availability,
    checkout_cart,
    get_product,
    remove_from_cart,
    search_products,
    view_cart,
    clear_cart,
    track_order,
)
from app.care.tools import emergency_info

logger = logging.getLogger("pharmacy-api.fast_path")


_REMOVAL_WITH_CART = re.compile(
    r"\b(?:remove|delete|take|drop|discard)\b\s+"
    r"(?:the\s+)?(?P<item>.+?)\s+"
    r"(?:from|out\s+of)\s+(?:my\s+)?(?:shopping\s+)?cart\b",
    re.IGNORECASE,
)

_REMOVAL_ITEM_ONLY = re.compile(
    r"^\s*(?:please\s+|can\s+you\s+|could\s+you\s+|would\s+you\s+|kindly\s+)?"
    r"(?:remove|delete|take|drop|discard)\s+(?:the\s+)?(?P<item>.+?)\s*[?.!]*$",
    re.IGNORECASE,
)

_VIEW_CART = re.compile(
    r"^\s*(?:please\s+)?(?:view|show|display|open)\s+"
    r"(?:me\s+)?(?:my\s+)?(?:shopping\s+)?cart\s*[?.!]*$",
    re.IGNORECASE,
)

# Tanglish/Tamil-mixed "what's in my cart" ("cart la enna irukku",
# "cart la what's there", "என் cart la என்ன இருக்கு") don't fit the
# strict English _VIEW_CART phrase shape above, so they're matched
# looser: the word "cart" plus a "what/is-there" cue word (English or
# Tamil), and no add/remove verb -- these are generic question/grammar
# words, not product names, same category as "view"/"show" above.
_CART_WORD = re.compile(r"\bcart\b", re.IGNORECASE)
_WHATS_IN_CART_CUE = re.compile(
    r"\b(?:what'?s|whats|what|enna|yenna)\b|"
    r"என்ன|இருக்கு|"  # என்ன, இருக்கு
    r"irukk|iruk[au]",
    re.IGNORECASE,
)
_CART_MUTATION_CUE = re.compile(
    r"\b(?:add|remove|delete|clear|empty|put|drop|order)\b",
    re.IGNORECASE,
)


def _is_loose_view_cart(message: str) -> bool:
    return bool(
        _CART_WORD.search(message)
        and _WHATS_IN_CART_CUE.search(message)
        and not _CART_MUTATION_CUE.search(message)
    )

_CLEAR_CART = re.compile(
    r"^\s*(?:please\s+)?(?:clear|empty|delete|remove)\s+"
    r"(?:out\s+)?(?:my\s+)?(?:shopping\s+)?cart\s*[?.!]*$",
    re.IGNORECASE,
)

_ADD_TO_CART = re.compile(
    r"^\s*(?:please\s+|can\s+you\s+|could\s+you\s+|would\s+you\s+|kindly\s+)?"
    r"add\s+(?:(?P<qty>\d+)\s+)?(?P<item>.+?)\s+"
    r"to\s+(?:my\s+)?(?:shopping\s+)?cart\s*[?.!]*$",
    re.IGNORECASE,
)

_ADD_TO_CART_PUT = re.compile(
    r"^\s*(?:please\s+)?put\s+(?:(?P<qty>\d+)\s+)?(?P<item>.+?)\s+"
    r"in(?:to)?\s+(?:my\s+)?(?:shopping\s+)?cart\s*[?.!]*$",
    re.IGNORECASE,
)

# "add to cart <item>" -- cart named before the item, the reverse word
# order from _ADD_TO_CART above ("add <item> to cart").
_ADD_TO_CART_PREFIX = re.compile(
    r"^\s*(?:please\s+)?add\s+(?:it\s+|this\s+|that\s+)?"
    r"to\s+(?:my\s+)?(?:shopping\s+)?cart\s+"
    r"(?:(?P<qty>\d+)\s+)?(?P<item>.+?)\s*[?.!]*$",
    re.IGNORECASE,
)

# Bare "add <item>" with no "cart" mentioned at all -- checked last, only
# once the more specific cart-phrase patterns above have already had a
# chance to match, so it can't shadow them.
_ADD_BARE = re.compile(
    r"^\s*(?:please\s+|can\s+you\s+|could\s+you\s+|would\s+you\s+|kindly\s+)?"
    r"add\s+(?:(?P<qty>\d+)\s+)?(?P<item>.+?)\s*[?.!]*$",
    re.IGNORECASE,
)

_ORDER_STATUS = re.compile(
    r"^\s*(?:please\s+)?(?:"
    r"(?:track|check|show|view|find)\s+(?:my\s+)?(?:latest\s+)?order(?:\s+status)?"
    r"|(?:my\s+)?order\s+status"
    r"|where(?:'s|\s+is)\s+my\s+(?:order|package|delivery)"
    r")\s*[?.!]*$",
    re.IGNORECASE,
)

# "order Dolo 650" / "buy Dolo 650" -- placing a NEW order for a named
# product, distinct from _ORDER_STATUS above (checking an existing
# order). Checked only after _ORDER_STATUS has already had a chance to
# match "order status"/"track order"/etc., so a status question is never
# misread as a product name here.
_ORDER_PRODUCT = re.compile(
    r"^\s*(?:please\s+|can\s+you\s+|could\s+you\s+|would\s+you\s+|kindly\s+)?"
    r"(?:order|buy|purchase)\s+(?:(?P<qty>\d+)\s+)?(?P<item>.+?)\s*[?.!]*$",
    re.IGNORECASE,
)

_CHECK_AVAILABILITY = re.compile(
    r"^\s*(?:please\s+)?(?:"
    r"is|are|check|does|do\s+you\s+have"
    r")\s+(?:the\s+)?(?P<item>.+?)\s+"
    r"(?:in\s*[- ]?stock|available|availability)\s*[?.!]*$",
    re.IGNORECASE,
)

_PRODUCT_SEARCH = re.compile(
    r"^\s*(?:please\s+)?(?:"
    r"search\s+for|search|find|look\s+up|look\s+for"
    r")\s+(?P<item>.+?)\s*[?.!]*$",
    re.IGNORECASE,
)

_EMERGENCY_INFO = re.compile(
    r"^\s*(?:please\s+)?(?:"
    r"(?:medical\s+)?emergency(?:\s+(?:info|information|help))?"
    r"|what\s+(?:should|do)\s+i\s+do\s+in\s+(?:an?\s+)?(?:medical\s+)?emergency"
    r")\s*[?.!]*$",
    re.IGNORECASE,
)


def _normalized(value: str) -> str:
    """Routing/matching-only normalization -- lowercase, collapse
    whitespace/punctuation. Uses `\\w` (Unicode-aware in `str` patterns,
    not restricted to a-z0-9) so Tamil and other non-Latin letters survive
    instead of being silently dropped; this is never applied to text that
    gets spoken back to the user, only to values compared against catalog
    entries for matching."""

    return " ".join(re.findall(r"\w+", value.casefold(), re.UNICODE))


def normalized_transcript(value: str) -> str:
    """Public wrapper for logging: the same routing-only normalization
    `handle_fast_path` matches against, never the text spoken back."""

    return _normalized(value)


def _requested_add_to_cart(message: str) -> tuple[str, int] | None:
    match = (
        _ADD_TO_CART.match(message)
        or _ADD_TO_CART_PUT.match(message)
        or _ADD_TO_CART_PREFIX.match(message)
        or _ADD_BARE.match(message)
    )

    if not match:
        return None

    item = match.group("item").strip(" .?!")

    if not item:
        return None

    qty = match.group("qty")

    return item, int(qty) if qty else 1


def _requested_removal_item(message: str) -> str | None:
    match = _REMOVAL_WITH_CART.search(message)

    if not match:
        match = _REMOVAL_ITEM_ONLY.match(message)

    if not match:
        return None

    item = match.group("item").strip(" .?!")

    return item or None


def _cart_product_match(
    item: str,
    cart_items: list[dict],
) -> dict | None:

    requested = _normalized(item)

    if not requested:
        return None

    if requested in {
        "this medicine",
        "that medicine",
        "this item",
        "that item",
    }:
        if len(cart_items) != 1:
            return None

        cart_item = cart_items[0]

        product_result = get_product(
            cart_item["product_id"]
        )

        product = (
            product_result.get("data")
            if product_result.get("success")
            else None
        )

        if not product:
            return None

        return {
            "cart_item": cart_item,
            "product": product,
        }

    matches = []

    for cart_item in cart_items:

        product_result = get_product(
            cart_item["product_id"]
        )

        product = (
            product_result.get("data")
            if product_result.get("success")
            else None
        )

        if not product:
            continue

        names = (
            product.get("name", ""),
            product.get("generic_name", ""),
        )

        if any(
            requested == _normalized(name)
            or requested in _normalized(name)
            or _normalized(name) in requested
            for name in names
            if name
        ):
            matches.append(
                {
                    "cart_item": cart_item,
                    "product": product,
                }
            )

    return matches[0] if len(matches) == 1 else None


def _resolve_available_product(item: str) -> dict | None:
    """Resolve a spoken product name to one unambiguous catalog entry.

    Only auto-resolves when exactly one product matches, mirroring
    `_cart_product_match`'s posture: anything ambiguous or unmatched
    returns None so the caller falls through to the LLM/agent path
    instead of guessing.
    """

    search_result = search_products(item)

    if not search_result.get("success"):
        return None

    products = search_result.get("data", {}).get("products", [])

    if len(products) == 1:
        return products[0]

    if not products:
        return None

    requested = _normalized(item)

    exact = [
        product
        for product in products
        if requested
        in (
            _normalized(product.get("name", "")),
            _normalized(product.get("generic_name", "")),
        )
    ]

    return exact[0] if len(exact) == 1 else None


def _detect_route(message: str) -> str | None:
    """Which fast_path pattern a message would be dispatched to, purely
    for [FAST_PATH_CHECK] logging -- mirrors the branch order in
    `_dispatch_fast_path` below without duplicating its DB-calling logic."""

    if _VIEW_CART.match(message) or _is_loose_view_cart(message):
        return "view_cart"

    if _CLEAR_CART.match(message):
        return "clear_cart"

    if _requested_add_to_cart(message):
        return "add_to_cart"

    if _requested_removal_item(message):
        return "remove_from_cart"

    if _CHECK_AVAILABILITY.match(message):
        return "check_availability"

    if _ORDER_STATUS.match(message):
        return "track_order"

    if _ORDER_PRODUCT.match(message):
        return "place_order"

    if _EMERGENCY_INFO.match(message):
        return "emergency_info"

    if _PRODUCT_SEARCH.match(message):
        return "product_search"

    return None


def detect_fast_path_route(message: str) -> str | None:
    """Public wrapper: which fast_path action (if any) a message would be
    dispatched to. Lets a caller log a routing decision *before* calling
    handle_fast_path, whose own dispatch can call tools synchronously as
    part of resolving the request -- logging order would otherwise show
    tool calls before the router decision that led to them."""

    return _detect_route(message.strip()) if message.strip() else None


def handle_fast_path(
    user_message: str,
    user_id: str,
) -> dict:
    """Zero-LLM fast path entry point.

    Logs the exact transcript this function received and normalized, the
    pattern it matched (if any), and whether it ultimately handled the
    request or fell through to the router/agent/LLM -- so a miss is
    always visible in the logs rather than silently falling through.
    """

    message = user_message.strip()
    normalized = _normalized(message)
    route = _detect_route(message) if message else None

    logger.info(
        '[FAST_PATH_CHECK] transcript="%s" normalized="%s" route=%s',
        user_message,
        normalized,
        route or "none",
    )

    # Commerce and cart operations are deliberately routed through
    # Commerce Agent.  Keep this callable's only direct response for urgent
    # emergency guidance so no alternate caller can bypass Router -> Agent.
    if route != "emergency_info":
        logger.info('[FAST_PATH_MISS] transcript="%s"', user_message)
        return {"handled": False}

    result = _dispatch_fast_path(message, user_id)

    if result.get("handled"):
        logger.info("[FAST_PATH_MATCH] action=%s", route or "unknown")
    else:
        logger.info('[FAST_PATH_MISS] transcript="%s"', user_message)

    return result


def _dispatch_fast_path(
    message: str,
    user_id: str,
) -> dict:

    if not message:
        return {
            "handled": False,
        }

    if _VIEW_CART.match(message) or _is_loose_view_cart(message):

        result = view_cart(user_id)

        if not result.get("success"):
            return {
                "handled": True,
                "response": result["error"]["message"],
            }

        data = result.get("data") or {}

        if data.get("empty"):
            return {
                "handled": True,
                "response": "Your cart is empty.",
            }

        items = data.get("items", [])

        response_lines = ["Your cart contains:"]

        for item in items:

            line = (
                f"- {item.get('product_name', 'Product')} "
                f"x {item.get('quantity', 1)}"
            )

            pharmacy = item.get("pharmacy_name")

            if pharmacy:
                line += f" from {pharmacy}"

            response_lines.append(line)

        return {
            "handled": True,
            "response": "\n".join(response_lines),
        }

    if _CLEAR_CART.match(message):

        result = clear_cart(user_id)

        if not result.get("success"):
            return {
                "handled": True,
                "response": result["error"]["message"],
            }

        data = result.get("data") or {}

        return {
            "handled": True,
            "response": data.get(
                "message",
                "Your cart has been cleared.",
            ),
        }

    add_request = _requested_add_to_cart(message)

    if add_request:

        item, quantity = add_request

        product = _resolve_available_product(item)

        if product is None:
            # Ambiguous or unmatched -- fall through to the LLM/agent
            # path instead of guessing which product was meant.
            return {
                "handled": False,
            }

        add_result = add_to_cart(
            product_id=product["id"],
            quantity=quantity,
            user_id=user_id,
        )

        if not add_result.get("success"):
            return {
                "handled": True,
                "response": add_result["error"]["message"],
            }

        quantity_phrase = (
            f"{quantity} x {product['name']}"
            if quantity > 1
            else product["name"]
        )

        return {
            "handled": True,
            "response": f"Added {quantity_phrase} to your cart.",
        }

    requested_item = _requested_removal_item(message)

    if requested_item:

        cart_result = view_cart(user_id)

        if not cart_result.get("success"):
            return {
                "handled": True,
                "response": cart_result["error"]["message"],
            }

        cart_data = cart_result.get("data") or {}

        match = _cart_product_match(
            requested_item,
            cart_data.get("items", []),
        )

        if not match:
            return {
                "handled": True,
                "response": "I couldn't find that item in your cart.",
            }

        removal_result = remove_from_cart(
            product_id=match["product"]["id"],
            user_id=user_id,
        )

        if not removal_result.get("success"):
            return {
                "handled": True,
                "response": removal_result["error"]["message"],
            }

        return {
            "handled": True,
            "response": (
                f"Removed {match['product']['name']} "
                "from your cart."
            ),
        }

    availability_match = _CHECK_AVAILABILITY.match(message)

    if availability_match:

        item = availability_match.group("item").strip(" .?!")

        product = _resolve_available_product(item)

        if product is None:
            # Ambiguous or unmatched -- fall through to the LLM/agent
            # path instead of guessing which product was meant.
            return {
                "handled": False,
            }

        availability_result = check_product_availability(
            product["id"]
        )

        if not availability_result.get("success"):
            return {
                "handled": True,
                "response": availability_result["error"]["message"],
            }

        availability = (
            availability_result.get("data") or {}
        ).get("availability", [])

        in_stock = [
            entry
            for entry in availability
            if entry.get("available")
        ]

        if not in_stock:
            return {
                "handled": True,
                "response": (
                    f"{product['name']} is currently out of "
                    "stock nearby."
                ),
            }

        pharmacy_names = ", ".join(
            entry.get("name", "a nearby pharmacy")
            for entry in in_stock
        )

        return {
            "handled": True,
            "response": (
                f"Yes, {product['name']} is in stock at "
                f"{pharmacy_names}."
            ),
        }

    if _ORDER_STATUS.match(message):

        result = track_order(
            user_id=user_id
        )

        if not result.get("success"):
            return {
                "handled": True,
                "response": result["error"]["message"],
            }

        data = result.get("data") or {}

        order_id = data.get("order_id")
        status = data.get("order_status")

        if order_id and status:
            return {
                "handled": True,
                "response": (
                    f"Your order {order_id} is currently "
                    f"{status}."
                ),
            }

        return {
            "handled": True,
            "response": "Your order status was retrieved.",
        }

    order_match = _ORDER_PRODUCT.match(message)

    if order_match:

        item = order_match.group("item").strip(" .?!")

        qty = order_match.group("qty")

        quantity = int(qty) if qty else 1

        product = _resolve_available_product(item)

        if product is None:
            # Ambiguous or unmatched -- fall through to the LLM/agent
            # path instead of guessing which product was meant.
            return {
                "handled": False,
            }

        add_result = add_to_cart(
            product_id=product["id"],
            quantity=quantity,
            user_id=user_id,
        )

        if not add_result.get("success"):
            return {
                "handled": True,
                "response": add_result["error"]["message"],
            }

        # add_to_cart only stages the item -- checkout_cart is the
        # existing tool that actually creates the order (same one the
        # commerce agent and "track order status" already read back
        # from), so "order X" produces a real order, not just a cart
        # update.
        order_result = checkout_cart(user_id=user_id)

        if not order_result.get("success"):
            return {
                "handled": True,
                "response": order_result["error"]["message"],
            }

        order_data = order_result.get("data") or {}

        order_id = order_data.get("order_id")

        total = order_data.get("total")

        total_phrase = (
            f" Total ₹{total:.2f}."
            if isinstance(total, (int, float))
            else ""
        )

        return {
            "handled": True,
            "response": (
                f"Order placed successfully. Order {order_id} for "
                f"{product['name']} is confirmed.{total_phrase}"
            ),
        }

    if _EMERGENCY_INFO.match(message):

        result = emergency_info()

        if isinstance(result, str):
            return {
                "handled": True,
                "response": result,
            }

        if not result.get("success"):
            return {
                "handled": True,
                "response": result["error"]["message"],
            }

        return {
            "handled": True,
            "response": result.get("data", ""),
        }

    # Checked last (after every more specific pattern above) since it's
    # the broadest match -- "find"/"look for" would otherwise shadow more
    # specific intents like order status.
    search_match = _PRODUCT_SEARCH.match(message)

    if search_match:

        item = search_match.group("item").strip(" .?!")

        result = search_products(item)

        if not result.get("success"):
            return {
                "handled": True,
                "response": result["error"]["message"],
            }

        products = (result.get("data") or {}).get("products", [])

        if not products:
            return {
                "handled": True,
                "response": f"I couldn't find any products matching {item}.",
            }

        names = ", ".join(product["name"] for product in products[:5])

        return {
            "handled": True,
            "response": f"I found: {names}.",
        }

    return {
        "handled": False,
    }
