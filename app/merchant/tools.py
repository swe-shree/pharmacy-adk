from app.database import database as DB
from app.tools.common import amount, safe_tool, text


def _merchant(merchant_id: str) -> dict:
    merchant = next((m for m in DB["merchants"] if m["id"] == merchant_id), None)
    if not merchant:
        raise ValueError("Merchant not found")
    return merchant


def _merchant_order(merchant_id: str, order_id: str) -> dict:
    order = next((o for o in DB["merchant_orders"] if o["merchant_id"] == merchant_id and o["id"] == order_id), None)
    if not order:
        raise ValueError("Merchant order not found")
    return order


@safe_tool
def get_merchant_profile(merchant_id: str = "merchant_001") -> dict:
    """Get the authenticated merchant's profile."""
    return dict(_merchant(text(merchant_id, "merchant_id")))


@safe_tool
def get_merchant_inventory(merchant_id: str = "merchant_001") -> dict:
    """List inventory quantities for a merchant."""
    merchant_id = text(merchant_id, "merchant_id")
    _merchant(merchant_id)
    products = {p["id"]: p for p in DB["products"]}
    return {"inventory": [{**dict(i), "product_name": products[i["product_id"]]["name"]} for i in DB["merchant_inventory"] if i["merchant_id"] == merchant_id]}


@safe_tool
def update_merchant_inventory(product_id: str, quantity: int, merchant_id: str = "merchant_001") -> dict:
    """Set a non-negative inventory quantity for a merchant product."""
    merchant_id, product_id, quantity = text(merchant_id, "merchant_id"), text(product_id, "product_id"), amount(quantity, "quantity")
    _merchant(merchant_id)
    item = next((i for i in DB["merchant_inventory"] if i["merchant_id"] == merchant_id and i["product_id"] == product_id), None)
    if not item:
        raise ValueError("Merchant inventory item not found")
    item["quantity"] = quantity
    return dict(item)


@safe_tool
def get_merchant_catalog(merchant_id: str = "merchant_001") -> dict:
    """List products currently listed by a merchant."""
    merchant_id = text(merchant_id, "merchant_id")
    _merchant(merchant_id)
    products = {p["id"]: p for p in DB["products"]}
    return {"products": [dict(products[i["product_id"]]) for i in DB["merchant_products"] if i["merchant_id"] == merchant_id and i["listed"]]}


@safe_tool
def list_merchant_orders(merchant_id: str = "merchant_001") -> dict:
    """List orders assigned to a merchant."""
    merchant_id = text(merchant_id, "merchant_id")
    _merchant(merchant_id)
    return {"orders": [dict(o) for o in DB["merchant_orders"] if o["merchant_id"] == merchant_id]}


@safe_tool
def get_merchant_order(order_id: str, merchant_id: str = "merchant_001") -> dict:
    """Get one merchant order."""
    return dict(_merchant_order(text(merchant_id, "merchant_id"), text(order_id, "order_id")))


@safe_tool
def update_merchant_order_status(order_id: str, status: str, merchant_id: str = "merchant_001") -> dict:
    """Update a merchant order to a supported fulfillment status."""
    status = text(status, "status")
    if status not in {"pending", "accepted", "packed", "shipped", "delivered", "cancelled"}:
        raise ValueError("Unsupported order status")
    order = _merchant_order(text(merchant_id, "merchant_id"), text(order_id, "order_id"))
    order["status"] = status
    return dict(order)


@safe_tool
def get_merchant_analytics(merchant_id: str = "merchant_001") -> dict:
    """Return deterministic summary metrics for a merchant."""
    merchant_id = text(merchant_id, "merchant_id")
    _merchant(merchant_id)
    orders = [o for o in DB["merchant_orders"] if o["merchant_id"] == merchant_id]
    inventory = [i for i in DB["merchant_inventory"] if i["merchant_id"] == merchant_id]
    return {"order_count": len(orders), "gross_value": sum(o["total"] for o in orders), "listed_sku_count": len([p for p in DB["merchant_products"] if p["merchant_id"] == merchant_id and p["listed"]]), "units_in_stock": sum(i["quantity"] for i in inventory)}


MERCHANT_TOOLS = [get_merchant_profile, get_merchant_inventory, update_merchant_inventory, get_merchant_catalog, list_merchant_orders, get_merchant_order, update_merchant_order_status, get_merchant_analytics]
