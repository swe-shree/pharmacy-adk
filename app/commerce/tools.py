from math import asin, cos, radians, sin, sqrt
from itertools import product as cartesian_product

from app.database import database as DB
from app.tools.common import amount, safe_tool, text


# ============================================================
# HELPERS
# ============================================================

def _product(product_id: str) -> dict:
    normalized = product_id.casefold()

    product = next(
        (
            p
            for p in DB["products"]
            if p["id"] == product_id
            or p["name"].casefold() == normalized
        ),
        None,
    )

    if not product:
        raise ValueError("Product not found")

    return product


def _user(user_id: str) -> dict:
    user = next(
        (
            item
            for item in DB["users"]
            if item["id"] == user_id
        ),
        None,
    )

    if not user:
        raise ValueError("User not found")

    return user


def _distance_km(first: dict, second: dict) -> float:
    """Calculate approximate great-circle distance from stored coordinates."""

    lat1 = radians(first["latitude"])
    lon1 = radians(first["longitude"])

    lat2 = radians(second["latitude"])
    lon2 = radians(second["longitude"])

    latitude_delta = lat2 - lat1
    longitude_delta = lon2 - lon1

    arc = (
        sin(latitude_delta / 2) ** 2
        + cos(lat1)
        * cos(lat2)
        * sin(longitude_delta / 2) ** 2
    )

    return 6371 * 2 * asin(sqrt(arc))


def _select_pharmacy(
    product_id: str,
    user_id: str,
    quantity: int,
    pharmacy_name: str | None = None,
) -> dict:

    user = _user(user_id)

    pharmacies = [
        p
        for p in DB["pharmacies"]
        if p["city"].casefold() == user["city"].casefold()
    ]

    if pharmacy_name:
        requested = pharmacy_name.casefold()

        pharmacies = [
            p
            for p in pharmacies
            if requested in p["name"].casefold()
        ]

        if not pharmacies:
            raise ValueError(
                "Requested pharmacy not found in the user's city"
            )

    candidates = []

    for pharmacy in pharmacies:

        inventory = next(
            (
                item
                for item in DB["inventory"]
                if item["pharmacy_id"] == pharmacy["id"]
                and item["product_id"] == product_id
            ),
            None,
        )

        if inventory and inventory["quantity"] >= quantity:

            candidates.append(
                {
                    **pharmacy,
                    "distance_km": round(
                        _distance_km(user, pharmacy),
                        2,
                    ),
                }
            )

    if not candidates:
        raise ValueError(
            "Product is unavailable at the requested or nearby pharmacies"
        )

    return min(
        candidates,
        key=lambda pharmacy: pharmacy["distance_km"],
    )


def _pharmacy_candidates(
    product_id: str,
    user_id: str,
    quantity: int,
) -> list[dict]:

    user = _user(user_id)

    candidates = []

    for pharmacy in DB["pharmacies"]:

        if (
            pharmacy["city"].casefold()
            != user["city"].casefold()
        ):
            continue

        inventory = next(
            (
                item
                for item in DB["inventory"]
                if item["pharmacy_id"] == pharmacy["id"]
                and item["product_id"] == product_id
            ),
            None,
        )

        if inventory and inventory["quantity"] >= quantity:

            candidates.append(
                {
                    **pharmacy,
                    "distance_km": round(
                        _distance_km(user, pharmacy),
                        2,
                    ),
                }
            )

    return candidates


# ============================================================
# CART
# ============================================================

def _cart(user_id: str) -> dict:
    """
    Get the user's active cart.

    If the user does not have an active cart,
    create one automatically.
    """

    user_id = text(user_id, "user_id")

    # Find existing active cart
    cart = next(
        (
            c
            for c in DB["carts"]
            if c["user_id"] == user_id
            and c["status"] == "active"
        ),
        None,
    )

    # Create a new active cart if none exists
    if not cart:

        cart = {
            "id": f"cart_{len(DB['carts']) + 1:03d}",
            "user_id": user_id,
            "status": "active",
        }

        DB["carts"].append(cart)

    # Get items belonging to this cart
    items = [
        dict(item)
        for item in DB["cart_items"]
        if item["cart_id"] == cart["id"]
    ]

    return {
        **cart,
        "items": items,
    }


def _cart_summary(cart: dict) -> dict:
    """Join cart rows with user, product, and pharmacy display data."""

    # Cart records are keyed by the authenticated user ID.  A separate user
    # profile row is optional for a read-only cart request, so do not turn an
    # otherwise valid empty-cart response into "User not found".
    user = next(
        (item for item in DB["users"] if item["id"] == cart["user_id"]),
        None,
    )

    products = {
        product["id"]: product
        for product in DB["products"]
    }

    pharmacies = {
        pharmacy["id"]: pharmacy
        for pharmacy in DB["pharmacies"]
    }

    items = []

    for item in cart["items"]:

        product = products.get(item["product_id"])
        pharmacy = pharmacies.get(
            item.get("pharmacy_id")
        )

        items.append(
            {
                "cart_id": item["cart_id"],
                "product_id": item["product_id"],
                "product_name": (
                    product["name"]
                    if product
                    else "Unknown product"
                ),
                "pharmacy_id": item.get("pharmacy_id"),
                "pharmacy_name": (
                    pharmacy["name"]
                    if pharmacy
                    else "Unknown pharmacy"
                ),
                "quantity": item["quantity"],
                "unit_price": (
                    product.get("price")
                    if product
                    else None
                ),
            }
        )

    return {
        "cart_id": cart["id"],
        "user_id": cart["user_id"],
        "user_name": user.get("name") if user else None,
        "cart_status": cart["status"],
        "items": items,
        "empty": not items,
        "message": (
            "Your cart is empty."
            if not items
            else "Your cart contents are listed below."
        ),
    }


# ============================================================
# ORDER HELPERS
# ============================================================

def _order_summary(order: dict) -> dict:
    """Join order items with user, product, and pharmacy display data."""

    user = _user(order["user_id"])

    products = {
        product["id"]: product
        for product in DB["products"]
    }

    pharmacies = {
        pharmacy["id"]: pharmacy
        for pharmacy in DB["pharmacies"]
    }

    items = []

    for item in order.get("items", []):

        product = products.get(item["product_id"])

        pharmacy = pharmacies.get(
            item.get("pharmacy_id")
        )

        items.append(
            {
                "product_id": item["product_id"],
                "product_name": (
                    item.get("name")
                    or (
                        product["name"]
                        if product
                        else "Unknown product"
                    )
                ),
                "pharmacy_id": item.get("pharmacy_id"),
                "pharmacy_name": (
                    pharmacy["name"]
                    if pharmacy
                    else "Unknown pharmacy"
                ),
                "quantity": item["quantity"],
                "unit_price": item.get(
                    "price",
                    product.get("price")
                    if product
                    else None,
                ),
            }
        )

    return {
        "user_id": user["id"],
        "user_name": user["name"],
        "order_id": order["id"],
        "order_status": order["status"],
        "total": order.get("total"),
        "items": items,
    }


# ============================================================
# PRODUCT TOOLS
# ============================================================

@safe_tool
def search_products(
    query: str,
    category: str | None = None,
) -> dict:
    """Search products by name, generic name, or optional category."""

    query = text(query, "query").casefold()

    category = (
        category.casefold().strip()
        if category
        else None
    )

    return {
        "products": [
            dict(product)
            for product in DB["products"]
            if (
                query in product["name"].casefold()
                or query in product["generic_name"].casefold()
                or query in product["category"].casefold()
            )
            and (
                not category
                or product["category"].casefold()
                == category
            )
        ]
    }


@safe_tool
def get_product(product_id: str) -> dict:
    """Get one product by exact identifier."""

    return _product(
        text(product_id, "product_id")
    )


# ============================================================
# PHARMACY TOOLS
# ============================================================

@safe_tool
def search_pharmacies(
    city: str = "Chennai",
    query: str | None = None,
) -> dict:
    """Find pharmacies in a city, optionally filtered by name."""

    city = text(city, "city").lower()

    return {
        "pharmacies": [
            dict(p)
            for p in DB["pharmacies"]
            if p["city"].lower() == city
            and (
                not query
                or query.lower() in p["name"].lower()
            )
        ]
    }


@safe_tool
def check_product_availability(
    product_id: str,
    city: str = "Chennai",
) -> dict:
    """List inventory availability for a product in a city."""

    product_id = text(product_id, "product_id")
    city = text(city, "city").lower()

    _product(product_id)

    pharmacies = {
        p["id"]: p
        for p in DB["pharmacies"]
        if p["city"].lower() == city
    }

    return {
        "availability": [
            {
                **pharmacies[
                    inventory["pharmacy_id"]
                ],
                "product_id": product_id,
                "quantity": inventory["quantity"],
                "available": inventory["quantity"] > 0,
            }
            for inventory in DB["inventory"]
            if (
                inventory["product_id"] == product_id
                and inventory["pharmacy_id"] in pharmacies
            )
        ]
    }


@safe_tool
def find_nearest_available_pharmacy(
    product_id: str,
    quantity: int = 1,
    user_id: str = "user_001",
) -> dict:
    """Find the nearest pharmacy with sufficient product stock."""

    product = _product(
        text(product_id, "product_id")
    )

    user_id = text(user_id, "user_id")
    quantity = amount(quantity)

    pharmacy = _select_pharmacy(
        product["id"],
        user_id,
        quantity,
    )

    return {
        "product_id": product["id"],
        "product_name": product["name"],
        "quantity_requested": quantity,
        "pharmacy": pharmacy,
    }


# ============================================================
# CART TOOLS
# ============================================================

@safe_tool
def get_cart(
    user_id: str = "user_001",
) -> dict:
    """Get the user's current active cart."""

    user_id = text(user_id, "user_id")

    return _cart_summary(
        _cart(user_id)
    )


@safe_tool
def view_cart(
    user_id: str = "user_001",
) -> dict:
    """Return the user's current active cart."""

    user_id = text(user_id, "user_id")

    return _cart_summary(
        _cart(user_id)
    )


@safe_tool
def add_to_cart(
    product_id: str,
    quantity: int = 1,
    user_id: str = "user_001",
    pharmacy_name: str | None = None,
) -> dict:
    """Add a product to the user's active cart."""

    product_id = text(
        product_id,
        "product_id",
    )

    user_id = text(
        user_id,
        "user_id",
    )

    quantity = amount(quantity)

    product = _product(product_id)

    pharmacy = _select_pharmacy(
        product["id"],
        user_id,
        quantity,
        pharmacy_name,
    )

    # Creates cart automatically if needed
    cart = _cart(user_id)

    item = next(
        (
            i
            for i in DB["cart_items"]
            if i["cart_id"] == cart["id"]
            and i["product_id"] == product["id"]
            and i["pharmacy_id"] == pharmacy["id"]
        ),
        None,
    )

    if item:
        item["quantity"] += quantity

    else:
        DB["cart_items"].append(
            {
                "cart_id": cart["id"],
                "product_id": product["id"],
                "pharmacy_id": pharmacy["id"],
                "quantity": quantity,
            }
        )

    return _cart_summary(
        _cart(user_id)
    )


@safe_tool
def add_medicines_to_cart(
    product_ids: list[str],
    quantity: int = 1,
    user_id: str = "user_001",
) -> dict:
    """Add multiple medicines to one cart."""

    if not isinstance(product_ids, list) or not product_ids:
        raise ValueError(
            "product_ids must contain at least one medicine"
        )

    user_id = text(user_id, "user_id")
    quantity = amount(quantity)

    # Creates active cart if needed
    cart = _cart(user_id)

    requested = []
    unavailable = []

    for product_id in product_ids:

        try:

            product = _product(
                text(product_id, "product_id")
            )

            candidates = _pharmacy_candidates(
                product["id"],
                user_id,
                quantity,
            )

            if not candidates:

                unavailable.append(
                    {
                        "requested": product_id,
                        "reason": "No sufficient stock nearby",
                    }
                )

            else:

                requested.append(
                    (
                        product,
                        candidates,
                    )
                )

        except ValueError as error:

            unavailable.append(
                {
                    "requested": product_id,
                    "reason": str(error),
                }
            )

    assignments = []

    if requested:

        for candidate_group in cartesian_product(
            *(
                candidates
                for _, candidates in requested
            )
        ):

            locations = {
                candidate["id"]
                for candidate in candidate_group
            }

            distance = sum(
                candidate["distance_km"]
                for candidate in candidate_group
            )

            assignments.append(
                (
                    len(locations),
                    distance,
                    candidate_group,
                )
            )

        _, _, selected = min(
            assignments,
            key=lambda choice: (
                choice[0],
                choice[1],
            ),
        )

        for (
            product,
            _,
        ), pharmacy in zip(
            requested,
            selected,
        ):

            item = next(
                (
                    item
                    for item in DB["cart_items"]
                    if item["cart_id"] == cart["id"]
                    and item["product_id"] == product["id"]
                    and item["pharmacy_id"] == pharmacy["id"]
                ),
                None,
            )

            if item:
                item["quantity"] += quantity

            else:
                DB["cart_items"].append(
                    {
                        "cart_id": cart["id"],
                        "product_id": product["id"],
                        "pharmacy_id": pharmacy["id"],
                        "quantity": quantity,
                    }
                )

    summary = _cart_summary(
        _cart(user_id)
    )

    summary["unavailable"] = unavailable

    summary["fulfillment_groups"] = [
        {
            "pharmacy_id": pharmacy_id,
            "pharmacy_name": next(
                pharmacy["name"]
                for pharmacy in DB["pharmacies"]
                if pharmacy["id"] == pharmacy_id
            ),
            "items": [
                item
                for item in summary["items"]
                if item["pharmacy_id"] == pharmacy_id
            ],
        }
        for pharmacy_id in sorted(
            {
                item["pharmacy_id"]
                for item in summary["items"]
            }
        )
    ]

    summary["message"] = (
        "Some medicines were unavailable; "
        "available medicines were added to the combined cart."
        if unavailable
        else "All requested medicines were added to the combined cart."
    )

    return summary


@safe_tool
def clear_cart(
    user_id: str = "user_001",
) -> dict:
    """Remove all items from the user's active cart."""

    user_id = text(user_id, "user_id")

    cart = _cart(user_id)

    removed_items = _cart_summary(cart)["items"]

    DB["cart_items"][:] = [
        item
        for item in DB["cart_items"]
        if item["cart_id"] != cart["id"]
    ]

    return {
        "cart_id": cart["id"],
        "user_id": user_id,
        "user_name": _user(user_id)["name"],
        "cart_status": cart["status"],
        "removed_items": removed_items,
        "empty": True,
        "message": (
            "Your cart is already empty."
            if not removed_items
            else "Your cart has been cleared and is now empty."
        ),
    }


@safe_tool
def remove_from_cart(
    product_id: str,
    user_id: str = "user_001",
) -> dict:
    """Remove one product from the active cart."""

    product_id = text(
        product_id,
        "product_id",
    )

    user_id = text(
        user_id,
        "user_id",
    )

    cart = _cart(user_id)

    existing_item = next(
        (
            item
            for item in DB["cart_items"]
            if item["cart_id"] == cart["id"]
            and item["product_id"] == product_id
        ),
        None,
    )

    if not existing_item:
        raise ValueError(
            "Product is not in the cart"
        )

    DB["cart_items"][:] = [
        item
        for item in DB["cart_items"]
        if not (
            item["cart_id"] == cart["id"]
            and item["product_id"] == product_id
        )
    ]

    return _cart_summary(
        _cart(user_id)
    )


@safe_tool
def update_cart_quantity(
    product_id: str,
    quantity: int,
    user_id: str = "user_001",
) -> dict:
    """Set an existing cart item's quantity."""

    product_id = text(
        product_id,
        "product_id",
    )

    user_id = text(
        user_id,
        "user_id",
    )

    quantity = amount(quantity)

    cart = _cart(user_id)

    item = next(
        (
            item
            for item in DB["cart_items"]
            if item["cart_id"] == cart["id"]
            and item["product_id"] == product_id
        ),
        None,
    )

    if not item:
        raise ValueError(
            "Cart item not found"
        )

    item["quantity"] = quantity

    return _cart_summary(
        _cart(user_id)
    )


# ============================================================
# ORDER TOOLS
# ============================================================

@safe_tool
def list_orders(
    user_id: str = "user_001",
) -> dict:
    """List all orders for a user."""

    user_id = text(
        user_id,
        "user_id",
    )

    return {
        "orders": [
            dict(order)
            for order in DB["orders"]
            if order["user_id"] == user_id
        ]
    }


@safe_tool
def get_order(
    order_id: str,
    user_id: str = "user_001",
) -> dict:
    """Get one order belonging to a user."""

    order_id = text(
        order_id,
        "order_id",
    )

    user_id = text(
        user_id,
        "user_id",
    )

    order = next(
        (
            order
            for order in DB["orders"]
            if order["id"] == order_id
            and order["user_id"] == user_id
        ),
        None,
    )

    if not order:
        raise ValueError(
            "Order not found"
        )

    return dict(order)


@safe_tool
def get_order_status(
    order_id: str | None = None,
    user_id: str = "user_001",
) -> dict:
    """Get the current status of a user's order."""

    user_id = text(
        user_id,
        "user_id",
    )

    if not order_id:

        order = next(
            (
                item
                for item in reversed(DB["orders"])
                if item["user_id"] == user_id
            ),
            None,
        )

    else:

        order_id = text(
            order_id,
            "order_id",
        )

        order = next(
            (
                item
                for item in DB["orders"]
                if item["id"] == order_id
                and item["user_id"] == user_id
            ),
            None,
        )

    if not order:
        raise ValueError(
            "Order not found"
        )

    return _order_summary(order)


def track_order(
    order_id: str | None = None,
    user_id: str = "user_001",
) -> dict:
    """Compatibility entrypoint for order tracking."""

    return get_order_status(
        order_id,
        user_id,
    )


def order_tracking(
    order_id: str | None = None,
    user_id: str = "user_001",
) -> dict:
    """Compatibility name for order tracking."""

    return get_order_status(
        order_id,
        user_id,
    )


@safe_tool
def checkout_cart(
    user_id: str = "user_001",
) -> dict:
    """Create an order from the user's active cart."""

    user_id = text(
        user_id,
        "user_id",
    )

    cart = _cart(user_id)

    if not cart["items"]:
        raise ValueError(
            "Cart is empty"
        )

    items = []
    total = 0.0

    # Validate inventory and calculate total
    for item in cart["items"]:

        product = _product(
            item["product_id"]
        )

        inventory = next(
            (
                record
                for record in DB["inventory"]
                if record["pharmacy_id"]
                == item["pharmacy_id"]
                and record["product_id"]
                == product["id"]
            ),
            None,
        )

        if (
            not inventory
            or inventory["quantity"]
            < item["quantity"]
        ):
            raise ValueError(
                f"{product['name']} is currently unavailable "
                "in the requested quantity"
            )

        items.append(
            {
                **item,
                "name": product["name"],
                "price": product["price"],
            }
        )

        total += (
            product["price"]
            * item["quantity"]
        )

    # Deduct inventory
    for item in cart["items"]:

        inventory = next(
            record
            for record in DB["inventory"]
            if record["pharmacy_id"]
            == item["pharmacy_id"]
            and record["product_id"]
            == item["product_id"]
        )

        inventory["quantity"] -= item["quantity"]

    # Create order
    order = {
        "id": f"order_{len(DB['orders']) + 1:03d}",
        "user_id": user_id,
        "status": "placed",
        "total": total,
        "items": items,
    }

    DB["orders"].append(order)

    # Complete current cart
    cart_record = next(
        item
        for item in DB["carts"]
        if item["id"] == cart["id"]
    )

    cart_record["status"] = "completed"

    return _order_summary(order)


def placed_order(
    user_id: str = "user_001",
) -> dict:
    """Compatibility name for placing an order."""

    return checkout_cart(user_id)


# ============================================================
# REWARDS
# ============================================================

@safe_tool
def get_rewards(
    user_id: str = "user_001",
) -> dict:
    """Get the recorded rewards balance."""

    return {
        "user_id": text(
            user_id,
            "user_id",
        ),
        "points": 240,
        "tier": "silver",
    }


@safe_tool
def redeem_rewards(
    points: int,
    user_id: str = "user_001",
) -> dict:
    """Redeem positive reward points."""

    return {
        "user_id": text(
            user_id,
            "user_id",
        ),
        "redeemed_points": amount(
            points,
            "points",
        ),
        "discount": round(
            points / 10,
            2,
        ),
    }


# ============================================================
# PHARMACY DETAILS
# ============================================================

@safe_tool
def get_pharmacy_details(
    pharmacy_id: str,
) -> dict:
    """Get a pharmacy by exact identifier."""

    pharmacy_id = text(
        pharmacy_id,
        "pharmacy_id",
    )

    pharmacy = next(
        (
            p
            for p in DB["pharmacies"]
            if p["id"] == pharmacy_id
        ),
        None,
    )

    if not pharmacy:
        raise ValueError(
            "Pharmacy not found"
        )

    return dict(pharmacy)


# ============================================================
# TOOL REGISTRY
# ============================================================

COMMERCE_TOOLS = [
    search_products,
    get_product,
    search_pharmacies,
    check_product_availability,
    find_nearest_available_pharmacy,

    get_cart,
    view_cart,
    add_to_cart,
    add_medicines_to_cart,
    clear_cart,
    remove_from_cart,
    update_cart_quantity,

    list_orders,
    get_order,
    get_order_status,
    checkout_cart,

    get_rewards,
    redeem_rewards,

    get_pharmacy_details,
]
