import os
import logging
import time
from typing import Any, Callable, Optional

import razorpay
from dotenv import load_dotenv

from config import DEFAULT_SPEND_LIMIT
from context import (
    durable_hints,
    expresses_no_preference,
    normalize_gender,
    normalize_size,
    scrub_constraints,
)
from negotiation import check_sizes, find_products, fetch_facets

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

load_dotenv()

razorpay_client = razorpay.Client(
    auth=(os.getenv("RAZORPAY_KEY_ID"), os.getenv("RAZORPAY_KEY_SECRET"))
)

# Preference keys the agent is allowed to persist ACCOUNT-WIDE. These describe
# the shopper, so they can reasonably shape any future search.
#
# `materials` is deliberately absent: a fabric belongs to a garment type, not to
# a person. Saving "linen" from "I want linen shirts" is what made every later
# search — trousers included — demand linen and return nothing. Fabric is held
# per-conversation, per-subject instead (see context.py).
PREFERENCE_FIELDS = ("colors", "brands", "categories", "budget_level", "style", "avoid")


def ask_user(question: str, options: Optional[list[str]] = None) -> dict[str, Any]:
    """Surface a clarifying question to the user.

    Args:
        question: The question to ask.
        options: Optional list of quick-reply options.

    Returns:
        Dict with question and options for frontend rendering.
    """
    logger.info(f"Asking user: {question}")
    return {
        "type": "question",
        "question": question,
        "options": options or []
    }


# Facet key -> how it's presented. Order here is the order shown in the modal.
FACET_PROMPTS = [
    ("colors", "Any colour preference?", True),
    ("price_bands", "What's your budget?", False),
    ("brands", "Any brand you lean towards?", True),
    ("materials", "Any fabric preference?", True),
]


def ask_preferences(
    arguments: dict[str, Any], session: dict[str, Any], thread: dict[str, Any]
) -> dict[str, Any]:
    """Build a skippable clarifying form from the choices that really exist.

    A vague request ("some shirts") produces vague results, but interrogating
    the shopper one question at a time is worse. This returns a single compact
    form the frontend shows as a modal, with options drawn from live catalogue
    facets so nothing offered is out of stock.

    Facets the shopper has already answered — this turn or via saved
    preferences — are dropped, and every remaining one is individually
    skippable.

    Args:
        arguments: `query` (the product type) plus whatever constraints the
            agent has already worked out, so they aren't asked again.
        session: Current user session, for gender and saved preferences.

    Returns:
        A form spec for the frontend, or `{"skip": ...}` when there's nothing
        worth asking — in which case the agent should just search.
    """
    query = arguments.get("query") or ""
    gender = normalize_gender(arguments.get("gender") or session.get("user", {}).get("gender"))

    facets = fetch_facets(query, gender)
    if not facets.get("count"):
        return {"skip": "no_matching_products", "query": query}

    # Only ACCOUNT-level tastes suppress a question. Fabric never does: it is
    # scoped to whatever the last conversation was about, so treating it as
    # "already known" is how a stale fabric silently filtered a new product
    # type without the shopper ever being asked.
    hints = durable_hints(session.get("preferences") or {})
    already_known = {
        "colors": arguments.get("colors") or hints.get("colors"),
        "brands": arguments.get("brands") or hints.get("brands"),
        "materials": arguments.get("materials"),
        "price_bands": arguments.get("budget"),
    }

    fields = []
    for key, question, multi in FACET_PROMPTS:
        if already_known.get(key) or key not in facets:
            continue
        fields.append(
            {
                "key": key,
                "question": question,
                "multiple": multi,
                "options": facets[key],
            }
        )

    if not fields:
        return {"skip": "nothing_to_ask", "query": query}

    logger.info(f"Asking preferences for '{query}': {[f['key'] for f in fields]}")
    return {
        "type": "preference_form",
        "query": query,
        "title": f"Let's narrow down {query}",
        "subtitle": f"{facets['count']} matches — answer what you like, skip the rest.",
        "fields": fields,
        "skippable": True,
    }


def list_options(
    arguments: dict[str, Any], session: dict[str, Any]
) -> dict[str, Any]:
    """Answer "what do you stock?" with the real values, as data to say out loud.

    A shopper asking which brands, colours, fabrics or prices exist for a
    product type wants a list, not a form and not a grid of cards. This reads
    the same live catalogue facets `ask_preferences` uses, but returns them
    untruncated and for the agent to state in its reply.

    Args:
        arguments: `query` (the product type, optionally with a style word such
            as "crew neck"), plus an optional gender override.
        session: Current user session, for the gender filter.

    Returns:
        Dict with `count`, `brands`, `colors`, `materials`, the price range and
        bands — or `{"count": 0}` when the store carries nothing matching.
    """
    query = arguments.get("query") or ""
    gender = normalize_gender(arguments.get("gender") or session.get("user", {}).get("gender"))

    facets = fetch_facets(query, gender, full=True)
    if not facets.get("count"):
        return {"query": query, "count": 0, "note": "Nothing in stock matches that."}

    logger.info(f"Listed options for '{query}': {facets.get('count')} matches")
    return {
        "query": query,
        "count": facets["count"],
        "brands": facets.get("brands") or [],
        "colors": facets.get("colors") or [],
        "materials": facets.get("materials") or [],
        "min_price": facets.get("min_price"),
        "max_price": facets.get("max_price"),
        "price_bands": [b["label"] for b in facets.get("price_bands") or []],
        "note": (
            "These are the real values in stock for this product type. State the "
            "ones the shopper asked about directly in your reply — this is a "
            "question about the catalogue, not a product listing, so no cards are "
            "shown and there is nothing to duplicate."
        ),
    }


def check_availability(
    arguments: dict[str, Any], session: dict[str, Any], thread: dict[str, Any]
) -> dict[str, Any]:
    """Answer "is THIS one available in <size>?" for products already on screen.

    Search filters by size, so everything shown fits — but that only covers the
    case where the shopper's size was known in advance. The far more common
    exchange is the shopper pointing at a card and naming a size: "do you have
    that one in large?". There is no search to run there; the answer is a stock
    lookup on one product, and it must be exact, so this goes straight to the
    seller's `/stock` endpoint rather than through its LLM.

    Args:
        arguments: `size` (defaults to the shopper's own) and optional
            `product_ids` (defaults to everything currently on screen).
        session: The shopper's account-level session, for their saved size.
        thread: The active conversation, for what was last shown.

    Returns:
        Per-product availability plus an explicit instruction for the
        unavailable ones — the model has to say "not in your size", not fold it
        into a vague "couldn't find anything".
    """
    on_screen = thread.get("last_shown") or []
    names = {item["id"]: item.get("name") for item in on_screen}

    product_ids = [pid for pid in (arguments.get("product_ids") or []) if pid]
    if not product_ids:
        product_ids = [item["id"] for item in on_screen]
    if not product_ids:
        return {
            "error": "no_products",
            "message": (
                "Nothing has been shown in this conversation yet, so there is no product "
                "to check. Search first, or ask which item they mean."
            ),
        }

    size = normalize_size(arguments.get("size") or session.get("user", {}).get("size"))
    if not size:
        return {
            "error": "no_size",
            "message": (
                "No size to check against. Ask the shopper which size they wear, then "
                "save it with update_profile."
            ),
        }

    stock = check_sizes(product_ids, size)
    if not stock:
        return {"error": "seller_unreachable", "size": size}

    by_id = stock.get("products") or {}
    available, unavailable = [], []
    for pid in product_ids:
        report = by_id.get(pid) or {}
        entry = {
            "id": pid,
            "name": report.get("name") or names.get(pid) or pid,
            "count": report.get("requested_size_count", 0),
            "available_sizes": report.get("available_sizes") or [],
        }
        (available if report.get("in_stock") else unavailable).append(entry)

    result: dict[str, Any] = {
        "size": size,
        "available": available,
        "unavailable": unavailable,
    }

    if unavailable:
        listed = "; ".join(
            f"{item['name']} (in stock in {', '.join(item['available_sizes'])})"
            if item["available_sizes"]
            else f"{item['name']} (sold out in every size)"
            for item in unavailable
        )
        result["note"] = (
            f"NOT available in {size}: {listed}. Say this plainly — name the item and the "
            f"sizes it does come in, and offer either a different size or to find "
            f"something similar that comes in {size}. Do not describe it as out of stock "
            f"generally, and do not add it to an order."
        )
    if available:
        low = [item for item in available if item["count"] <= 2]
        if low:
            result["low_stock_note"] = (
                "Running low: "
                + ", ".join(f"{item['name']} ({item['count']} left in {size})" for item in low)
            )

    logger.info(f"Availability check size={size}: {len(available)} yes, {len(unavailable)} no")
    return result


def _cart_line(cart: list[dict[str, Any]], product_id: str, size: Optional[str]):
    """The cart line for a product in a size, or the only line for it.

    Falling back to "the only line" matters because the shopper rarely says a
    size when there's no ambiguity: "drop the blue shirt" should work when
    that shirt is in the cart exactly once.
    """
    if size:
        match = next(
            (e for e in cart if e.get("id") == product_id and normalize_size(e.get("size")) == size),
            None,
        )
        if match:
            return match
    lines = [e for e in cart if e.get("id") == product_id]
    return lines[0] if len(lines) == 1 else None


def add_to_cart(
    arguments: dict[str, Any], session: dict[str, Any], thread: dict[str, Any]
) -> dict[str, Any]:
    """Put products the shopper agreed to onto the cart, in the sizes they named.

    The cart used to be the frontend's alone, so "yes, add those three" left the
    agent with nothing to call: it said it had added them, the cart stayed
    empty, and the shopper's next screen disagreed with the last thing they were
    told. Adding is a normal part of the conversation, so it gets a tool.

    Product records come from what was actually shown in THIS conversation
    (`shown_catalog`), never from the model — a cart line carries a price, a
    stocked-size map and an image, and none of those may be invented. A size
    with no stock is refused here exactly as it is at checkout, so an unbuyable
    line can't be created in the first place.

    Args:
        arguments: `items`, a list of `{product_id, size?, quantity?}`. A single
            `product_id`/`size`/`quantity` at the top level is also accepted.
        session: The shopper's account-level session (holds "cart" and their size).
        thread: The active conversation, for the products it has shown.

    Returns:
        Dict with the updated cart plus `added` and `rejected` lists, so the
        reply can name anything that didn't go in and why.
    """
    cart = session.setdefault("cart", [])
    catalog = thread.get("shown_catalog") or {}
    default_size = normalize_size(session.get("user", {}).get("size"))

    items = arguments.get("items")
    if not items:
        if arguments.get("product_id"):
            items = [
                {
                    "product_id": arguments["product_id"],
                    "size": arguments.get("size"),
                    "quantity": arguments.get("quantity"),
                }
            ]
        else:
            return {
                "error": "no_items",
                "message": "Say which product IDs to add, from the products currently on screen.",
            }

    added: list[dict[str, Any]] = []
    rejected: list[dict[str, Any]] = []

    for item in items:
        product_id = (item or {}).get("product_id")
        product = catalog.get(product_id)
        if not product:
            rejected.append(
                {
                    "product_id": product_id,
                    "reason": "not_shown",
                    "message": (
                        "That item hasn't been shown in this conversation, so it can't be "
                        "added yet. Search for it first, then add it from the results — do "
                        "not mention its internal ID to the shopper."
                    ),
                }
            )
            continue

        sizes = product.get("sizes") or {}
        size = normalize_size(item.get("size")) or default_size
        if not size:
            rejected.append(
                {
                    "product_id": product_id,
                    "name": product.get("name"),
                    "reason": "no_size",
                    "available_sizes": [s for s, n in sizes.items() if n > 0],
                    "message": (
                        f"No size given for {product.get('name')} and none saved on the "
                        f"profile. Ask which size they wear."
                    ),
                }
            )
            continue

        stocked = sizes.get(size)
        if stocked is not None and stocked <= 0:
            rejected.append(
                {
                    "product_id": product_id,
                    "name": product.get("name"),
                    "reason": "size_out_of_stock",
                    "requested_size": size,
                    "available_sizes": [s for s, n in sizes.items() if n > 0],
                    "message": (
                        f"{product.get('name')} is not stocked in {size}, so it was not "
                        f"added. Offer the sizes it does come in."
                    ),
                }
            )
            continue

        quantity = int(item.get("quantity") or 1)
        if quantity < 1:
            quantity = 1

        existing = _cart_line_exact(cart, product_id, size)
        if existing:
            existing["quantity"] = existing.get("quantity", 1) + quantity
            line = existing
        else:
            line = {**product, "size": size, "quantity": quantity}
            cart.append(line)

        added.append(
            {
                "product_id": product_id,
                "name": product.get("name"),
                "size": size,
                "quantity": line.get("quantity", 1),
                "price": product.get("price"),
            }
        )

    logger.info(f"Cart add: {len(added)} added, {len(rejected)} rejected")

    result: dict[str, Any] = {
        "status": "ok" if added else "nothing_added",
        # `cart_updated` is what tells the frontend to replace its own copy, so
        # the cart button appears the moment the agent adds something. Sent even
        # when nothing went in is wrong — it would blank a cart the UI has.
        "cart": cart,
        "added": added,
        "rejected": rejected,
    }
    if added:
        result["cart_updated"] = True
        result["note"] = (
            "Added. Confirm what went in with the size for each line, then ask whether "
            "they want to check out or keep looking. Do not call checkout_cart unless "
            "they ask for it."
        )
    return result


def _cart_line_exact(cart: list[dict[str, Any]], product_id: str, size: Optional[str]):
    """The cart line for exactly this product in exactly this size, or None.

    Distinct from `_cart_line`, which falls back to "the only line for it" so a
    shopper can say "drop the blue shirt" without a size. That fallback is
    wrong when ADDING: the same shirt in M and in L are two lines, and matching
    loosely would silently bump the M when the shopper asked for an L.
    """
    return next(
        (
            e
            for e in cart
            if e.get("id") == product_id and normalize_size(e.get("size")) == size
        ),
        None,
    )


def update_cart(arguments: dict[str, Any], session: dict[str, Any]) -> dict[str, Any]:
    """Change a cart line's size or quantity, or remove it, on the shopper's say-so.

    Checkout can refuse a line — wrong size, not enough units — and the reply
    that follows is almost always "make it M then". Without this the agent has
    to send the shopper to the cart UI to do something it was just asked to do,
    which reads as a refusal. The same guard as the UI applies: a size with no
    stock cannot be selected here either.

    Args:
        arguments: `product_id`, optional `size` (which line), and any of
            `new_size`, `quantity`, `remove`.
        session: Current user session (contains "cart").

    Returns:
        Dict with the updated cart, or an error naming what went wrong.
    """
    cart = session.setdefault("cart", [])
    product_id = arguments.get("product_id")
    line = _cart_line(cart, product_id, normalize_size(arguments.get("size")))

    if not line:
        return {
            "error": "line_not_found",
            "cart": cart,
            "message": (
                "No single cart line matches. If the product is in the cart in more than "
                "one size, say which size to change."
            ),
        }

    if arguments.get("remove"):
        cart.remove(line)
        logger.info(f"Cart line removed: {product_id}")
        return {"status": "ok", "cart": cart, "cart_updated": True, "removed": product_id}

    new_size = normalize_size(arguments.get("new_size"))
    if new_size:
        stocked = (line.get("sizes") or {}).get(new_size)
        if stocked is not None and stocked <= 0:
            return {
                "error": "size_out_of_stock",
                "cart": cart,
                "requested_size": new_size,
                "available_sizes": [
                    size for size, n in (line.get("sizes") or {}).items() if n > 0
                ],
                "message": (
                    f"{line.get('name')} is not stocked in {new_size}, so the cart was not "
                    f"changed. Offer the sizes it does come in."
                ),
            }
        # Merge rather than leave two lines the shopper has to reconcile later.
        target = next(
            (
                e
                for e in cart
                if e is not line
                and e.get("id") == product_id
                and normalize_size(e.get("size")) == new_size
            ),
            None,
        )
        if target:
            target["quantity"] = target.get("quantity", 1) + line.get("quantity", 1)
            cart.remove(line)
            line = target
        else:
            line["size"] = new_size

    quantity = arguments.get("quantity")
    if quantity is not None:
        quantity = int(quantity)
        if quantity <= 0:
            cart.remove(line)
            return {"status": "ok", "cart": cart, "cart_updated": True, "removed": product_id}
        line["quantity"] = quantity

    logger.info(f"Cart line updated: {product_id} -> size={line.get('size')} x{line.get('quantity')}")
    return {"status": "ok", "cart": cart, "cart_updated": True, "line": line}


def checkout_cart(session: dict[str, Any], confirm_over_limit: bool = False) -> dict[str, Any]:
    """Create a Razorpay order for the user's current session cart.

    Reads buyer details and cart contents directly from the session so the
    LLM never has to transcribe product IDs or sum amounts itself.

    Args:
        session: Current user session (contains "user" and "cart").
        confirm_over_limit: True only once the shopper has explicitly
            confirmed, through the app's own dialog, that they want to proceed
            despite exceeding their auto-approve spend limit. Set by
            main.py's deterministic override-phrase check, not by the model's
            own judgement.

    Returns:
        Dict with order details, or an "error" key describing why checkout
        could not proceed (empty cart, missing buyer info, a line that can't
        ship in the size it was ordered in, the total exceeding the shopper's
        spend limit, or a Razorpay failure).
    """
    user = session.get("user", {})
    cart = session.get("cart", [])

    if not cart:
        return {"error": "cart_empty"}

    required_fields = ["email", "phone", "address", "payment_method"]
    missing = [field for field in required_fields if not user.get(field)]
    if missing:
        return {"error": "missing_buyer_info", "missing": missing}

    product_ids = [item["id"] for item in cart]

    # Last word on whether this can actually ship. Each line is checked in ITS
    # OWN size — the cart can legitimately hold the same shirt in M and in L,
    # and validating both against one size would clear a line that can't ship
    # while blocking one that can. Quantity is checked too: 3 ordered against 2
    # in stock is the same failure, one step later.
    default_size = normalize_size(user.get("size"))
    by_size: dict[str, list[dict[str, Any]]] = {}
    for item in cart:
        size = normalize_size(item.get("size")) or default_size
        if size:
            by_size.setdefault(size, []).append(item)

    blocked: list[dict[str, Any]] = []
    for size, items in by_size.items():
        stock = check_sizes([i["id"] for i in items], size)
        if not stock:
            # Seller unreachable. Unknown is not the same as unavailable, and
            # blocking checkout on a failed health check is the worse error.
            continue
        reports = stock.get("products") or {}
        for item in items:
            report = reports.get(item["id"]) or {}
            in_stock = report.get("requested_size_count", 0)
            wanted = item.get("quantity", 1)
            if report.get("in_stock") and in_stock >= wanted:
                continue
            blocked.append(
                {
                    "id": item["id"],
                    "name": report.get("name") or item.get("name") or item["id"],
                    "size": size,
                    "quantity": wanted,
                    "in_stock": in_stock,
                    "available_sizes": report.get("available_sizes") or [],
                    "reason": "out_of_stock" if in_stock == 0 else "insufficient_quantity",
                }
            )

    if blocked:
        return {
            "error": "size_unavailable",
            "items": blocked,
            "message": (
                "Some lines cannot ship as ordered. For each one, tell the shopper the "
                "item, the size they picked, and why — either it is not stocked in that "
                "size (name the sizes it IS in) or there aren't enough units left. Ask "
                "them to change the size or reduce the quantity in the cart. Do not "
                "retry checkout unchanged."
            ),
        }

    amount = sum(item["price"] * item.get("quantity", 1) for item in cart)

    # Code-level guardrail, independent of the LLM: an order over the
    # shopper's auto-approve limit cannot reach Razorpay unless the shopper
    # has already confirmed the override through the app's own dialog. Cart
    # and stock are untouched at this point, so blocking here has no side
    # effects to undo.
    spend_limit = user.get("spend_limit") or DEFAULT_SPEND_LIMIT
    if amount > spend_limit and not confirm_over_limit:
        logger.info(f"Checkout blocked by spend limit: amount={amount} limit={spend_limit}")
        return {
            "error": "spend_limit_exceeded",
            "amount_inr": amount,
            "spend_limit": spend_limit,
            "over_by": amount - spend_limit,
            "message": (
                f"This order is Rs {amount:,}, above the shopper's Rs {spend_limit:,} "
                f"auto-approve limit. The app is showing them a Confirm/Cancel dialog "
                f"directly — say the total and the limit in one line, do not call "
                f"ask_user, and do not retry checkout_cart yourself."
            ),
        }

    try:
        order = razorpay_client.order.create(
            {
                "amount": amount * 100,
                "currency": "INR",
                "receipt": f"receipt_{'_'.join(product_ids[:3])}",
            }
        )

        logger.info(f"Order created: {order['id']} for products: {product_ids}")

        lines = [
            {
                "id": item["id"],
                "name": item.get("name"),
                "brand": item.get("brand"),
                "size": normalize_size(item.get("size")) or default_size,
                "quantity": item.get("quantity", 1),
                "price": item.get("price"),
            }
            for item in cart
        ]
        buyer = {
            "name": user.get("name", ""),
            "email": user.get("email", ""),
            "phone": user.get("phone", ""),
            "address": user.get("address", ""),
        }
        # Tracked so verify_payment can tell a first confirmation from a repeat
        # one and never re-process an order already marked paid, and so the
        # receipts page has a real record to render without a second lookup —
        # a card would otherwise have nothing to show until this order is
        # separately re-fetched from Razorpay.
        session.setdefault("orders", {})[order["id"]] = {
            "status": "created",
            "amount_inr": amount,
            "currency": order["currency"],
            "lines": lines,
            "buyer": buyer,
            "created_at": time.time(),
        }
        session["cart"] = []

        return {
            "order_id": order["id"],
            # Razorpay works in paise and the frontend passes `amount` straight
            # to the checkout SDK, so it has to stay in paise. The model reads
            # this dict too and was quoting the paise figure as rupees — two
            # ₹1,049 shirts came back as "₹209,800". `amount_inr` is the one to
            # say out loud, and the note is here because a bare pair of numbers
            # is exactly the ambiguity that caused the bug.
            "amount": order["amount"],
            "amount_inr": order["amount"] // 100,
            "amount_note": (
                f"Quote ₹{order['amount'] // 100:,} to the shopper. `amount` is in paise "
                f"for the payment SDK — never state it as rupees."
            ),
            "currency": order["currency"],
            "product_ids": product_ids,
            "lines": lines,
            "buyer": buyer,
            "status": "created",
            "message": "Order created. Complete payment in the checkout modal.",
        }
    except Exception as e:
        logger.error(f"Razorpay error: {e}")
        return {"error": "order_creation_failed"}


def update_profile(arguments: dict[str, Any], session: dict[str, Any]) -> dict[str, Any]:
    """Save profile fields collected conversationally onto the session.

    Anything collected here — typically the address or phone the shopper only
    gives up at checkout — is the same record Settings reads, so the details
    they type into the chat show up in their profile without being re-entered.

    Args:
        arguments: Any of name/email/phone/address/payment_method/gender/size.
        session: Current user session (contains "user").

    Returns:
        Dict with the updated user profile.
    """
    user = session.setdefault("user", {})

    # `spend_limit` is deliberately absent: it's a safety ceiling set in
    # Settings, not something to negotiate in chat — letting update_profile
    # touch it would let a shopper talk the agent into raising their own
    # guardrail.
    for field in ("name", "email", "phone", "address", "payment_method", "gender", "size"):
        value = arguments.get(field)
        if value:
            user[field] = value

    if arguments.get("gender"):
        user["gender_normalized"] = normalize_gender(arguments["gender"])
    if arguments.get("size"):
        # Stored normalised so every later search compares against the
        # catalogue's own key rather than whatever the shopper typed.
        user["size"] = normalize_size(arguments["size"]) or arguments["size"]

    logger.info(f"Profile updated for {user.get('email', 'unknown')}: {list(arguments.keys())}")
    # `profile_updated` is what tells the frontend to refresh Settings from the
    # server, so details given mid-chat don't sit only in the agent's session.
    return {"status": "ok", "user": user, "profile_updated": True}


def save_preferences(arguments: dict[str, Any], session: dict[str, Any]) -> dict[str, Any]:
    """Persist durable shopping preferences onto the session.

    These outlive the current message and are replayed into every future turn's
    system prompt, which is what lets "more like CASIO" or "I prefer grey" keep
    shaping results several turns later instead of being forgotten as soon as
    they scroll out of the history window.

    List-valued preferences merge rather than replace, so mentioning a second
    favourite brand doesn't erase the first.

    Only save what is true of the SHOPPER, not of the current request. A colour
    named for one garment ("a black linen shirt") is a search constraint and
    belongs to that conversation; "I always wear black" is a preference. Fabric
    is rejected outright here — it is never a durable property of a person.

    Args:
        arguments: Any of colors/brands/categories/budget_level/style/avoid.
        session: Current user session.

    Returns:
        Dict with the merged preference set.
    """
    preferences = session.setdefault("preferences", {})

    for field in PREFERENCE_FIELDS:
        value = arguments.get(field)
        if not value:
            continue
        if isinstance(value, list):
            existing = preferences.get(field) or []
            merged = list(dict.fromkeys([*existing, *[v for v in value if v]]))
            preferences[field] = merged
        else:
            preferences[field] = value

    ignored = sorted(set(arguments) - set(PREFERENCE_FIELDS))
    logger.info(f"Preferences saved: {preferences} (ignored: {ignored})")

    result: dict[str, Any] = {"status": "ok", "preferences": preferences, "preferences_updated": True}
    if ignored:
        result["ignored_fields"] = ignored
        if "materials" in ignored:
            result["note"] = (
                "Fabric is not saved as a lasting preference — it applies only to the "
                "product type currently being discussed. Pass it to find_products for "
                "this search instead."
            )
    return result


def clear_preferences(arguments: dict[str, Any], session: dict[str, Any]) -> dict[str, Any]:
    """Forget saved preferences, either a few fields or all of them.

    The counterpart to save_preferences. Without it a preference the shopper
    once mentioned could only be removed from Settings, so "actually, forget
    the black thing" had no effect on the very next search.

    Args:
        arguments: `fields` (list of preference keys) — omit to clear everything.
        session: Current user session.

    Returns:
        Dict with whatever preferences remain.
    """
    preferences = session.setdefault("preferences", {})
    fields = [f for f in (arguments.get("fields") or []) if f in PREFERENCE_FIELDS]

    if fields:
        cleared = [f for f in fields if preferences.pop(f, None) is not None]
    else:
        cleared = sorted(preferences)
        preferences.clear()

    logger.info(f"Preferences cleared: {cleared or 'nothing to clear'}")
    return {
        "status": "ok",
        "cleared": cleared,
        "preferences": preferences,
        "preferences_updated": True,
    }


def verify_payment(
    session: dict[str, Any], order_id: str, payment_id: Optional[str] = None
) -> dict[str, Any]:
    """Verify payment status for an order.

    Prefers looking up the payment itself (authoritative capture status) over
    the order aggregate, since the caller may pass the two IDs swapped — the
    LLM is handed both an order_id and a payment_id in the same sentence and
    isn't a reliable router between them.

    An order already recorded as paid is not re-verified against Razorpay: the
    stored result is returned as-is. Without this, a shopper (or an agent)
    resending the same payment-completion message would look identical to a
    fresh confirmation, which is exactly the double-processing this guards
    against — verifying is harmless today since nothing here ships or charges
    again on a repeat call, but the same order record is what a real
    fulfillment step would key off, so it must not look "freshly confirmed"
    twice.

    Args:
        session: Current user session (contains "orders", the local order
            status ledger keyed by Razorpay order_id).
        order_id: The Razorpay order ID.
        payment_id: The Razorpay payment ID, if known.

    Returns:
        Dict with payment status.
    """
    orders = session.setdefault("orders", {})
    existing = orders.get(order_id)
    if existing and existing.get("status") == "paid":
        logger.info(f"verify_payment short-circuit: {order_id} already marked paid")
        return {**existing.get("result", {}), "already_verified": True}

    try:
        if payment_id:
            payment = razorpay_client.payment.fetch(payment_id)
            logger.info(f"Payment verified for {payment_id}: {payment['status']}")
            result = {
                "order_id": payment.get("order_id", order_id),
                "payment_id": payment_id,
                "status": payment["status"],
                "amount": payment["amount"],
                "amount_inr": payment["amount"] // 100,
                "amount_note": f"Quote ₹{payment['amount'] // 100:,} — `amount` is in paise.",
            }
        else:
            order = razorpay_client.order.fetch(order_id)
            logger.info(f"Payment verified for {order_id}: {order['status']}")
            result = {
                "order_id": order["id"],
                "status": order["status"],
                "amount": order["amount"],
                "amount_inr": order["amount"] // 100,
                "amount_note": f"Quote ₹{order['amount'] // 100:,} — `amount` is in paise.",
            }
    except Exception as e:
        logger.error(f"Payment verification error: {e}")
        return {"error": "verification_failed"}

    if result.get("status") in ("captured", "paid"):
        # Merged onto the existing record rather than replacing it — checkout_cart
        # already stored the line items and buyer details a receipt needs, and
        # overwriting the record here would blank a receipt back to just a status.
        orders[order_id] = {
            **orders.get(order_id, {}),
            "status": "paid",
            "payment_id": result.get("payment_id"),
            "paid_at": time.time(),
            "result": result,
        }
    else:
        orders.setdefault(order_id, {"status": "created"})
    return result


def extract_structured_payload(tool_results: list[dict[str, Any]]) -> dict[str, Any]:
    """Pull structured product/option data out of a round's tool results.

    The frontend renders cards from this rather than regex-parsing the reply
    text. Primary results and cross-sell suggestions are kept apart so the UI
    can label them differently — a complement shown as a main result reads as
    the agent ignoring the request.

    Args:
        tool_results: The tool_results list produced during a /chat round.

    Returns:
        Dict with `products`, `complements`, `options`, `form` (the clarifying
        modal spec, or None), `profile_dirty` — a flag telling the frontend
        that details or preferences changed mid-chat and Settings should be
        refreshed — and `cart`, present only when the agent changed it, so the
        frontend can replace its own copy instead of drifting out of sync.
    """
    products: list[dict[str, Any]] = []
    complements: list[dict[str, Any]] = []
    seen_ids: set[str] = set()
    options: Optional[list[str]] = None
    form: Optional[dict[str, Any]] = None
    profile_dirty = False
    cart: Optional[list[dict[str, Any]]] = None

    for tr in tool_results:
        result = tr.get("result") or {}

        if result.get("profile_updated") or result.get("preferences_updated"):
            profile_dirty = True

        if result.get("cart_updated"):
            cart = result.get("cart")

        if tr.get("tool") == "ask_preferences":
            if result.get("type") == "preference_form":
                form = result

        elif tr.get("tool") == "find_products":
            bucket = complements if result.get("purpose") == "complement" else products
            for product in result.get("products", []):
                product_id = product.get("id")
                if product_id and product_id not in seen_ids:
                    seen_ids.add(product_id)
                    bucket.append(product)

        elif tr.get("tool") == "ask_user":
            tool_options = result.get("options")
            if tool_options:
                options = tool_options

    return {
        "products": products,
        "complements": complements,
        "options": options,
        "form": form,
        "profile_dirty": profile_dirty,
        "cart": cart,
    }


def _prepare_search(
    arguments: dict[str, Any],
    session: dict[str, Any],
    thread: dict[str, Any],
    turn_text: str,
) -> tuple[dict[str, Any], list[str]]:
    """Resolve a search's real constraints before anything is sent to the seller.

    Two things happen in code rather than in the prompt, because both were
    unreliable when left to the model:

    1. Stale constraints are stripped (`scrub_constraints`) — a fabric or colour
       from the last product type can't survive into a new one unless the
       shopper repeated it.
    2. Gender and size are filled in from the profile. Both are details, not
       preferences, and every search should respect them without being told to
       each turn. Neither is guessed: an unrecognised value resolves to no
       filter, because showing the whole catalogue beats hiding it behind a
       constraint the shopper never set.
    """
    constraints, notes = scrub_constraints(arguments, thread, turn_text)

    if not constraints.get("ignore_saved_preferences"):
        hints = durable_hints(session.get("preferences") or {})
        # Durable tastes fill gaps only. Anything the shopper said this turn
        # already won, and anything scrubbed above stays gone.
        for key in ("colors", "brands"):
            if hints.get(key) and not constraints.get(key):
                constraints[key] = list(hints[key])
                notes.append(f"Applied your saved {key} preference ({', '.join(hints[key])}).")

    gender = normalize_gender(constraints.get("gender") or session.get("user", {}).get("gender"))
    if gender:
        constraints["gender"] = gender
    else:
        constraints.pop("gender", None)

    # An explicit size in the tool call wins — that's the shopper buying for
    # someone else. Otherwise their own size applies, and it is never dropped
    # by scrubbing or by "no preference": a garment that doesn't fit is not a
    # result no matter how relaxed the rest of the ask becomes.
    size = normalize_size(constraints.get("size") or session.get("user", {}).get("size"))
    if size:
        constraints["size"] = size
    else:
        constraints.pop("size", None)

    return constraints, notes


def execute_tool(
    tool_name: str,
    arguments: dict[str, Any],
    session: dict[str, Any],
    thread: dict[str, Any],
    turn_text: str = "",
    emit: Optional[Callable[[str, dict[str, Any]], None]] = None,
) -> dict[str, Any]:
    """Execute a tool by name with given arguments.

    Args:
        tool_name: Name of the tool to execute.
        arguments: Tool arguments as produced by the model.
        session: The shopper's account-level session (profile, durable prefs, cart).
        thread: The active conversation's state (history, subject, seen products).
        turn_text: The shopper's message for this turn, used to decide which
            carried-over constraints they actually restated.
        emit: Optional progress callback forwarded to long-running tools so the
            UI can narrate the seller negotiation while it happens.

    Returns:
        Tool execution result.
    """
    logger.info(f"Executing tool: {tool_name}")

    if tool_name == "find_products":
        constraints, notes = _prepare_search(arguments, session, thread, turn_text)
        result = find_products(constraints, session, thread, emit=emit)
        if notes:
            # Surfaced to the model so its reply matches what was actually
            # searched for — otherwise it apologises for not finding linen
            # trousers nobody asked for.
            result["context_note"] = " ".join(notes)
        return result

    if tool_name == "ask_preferences":
        constraints, _ = _prepare_search(arguments, session, thread, turn_text)
        if constraints.get("ignore_saved_preferences"):
            # They've just told us they don't mind. Asking them to pick colours
            # and fabrics immediately after is the opposite of listening.
            return {"skip": "shopper_declined_preferences", "query": constraints.get("query", "")}
        return ask_preferences(constraints, session, thread)

    if tool_name == "list_options":
        return list_options(arguments, session)

    if tool_name == "check_availability":
        return check_availability(arguments, session, thread)

    if tool_name == "ask_user":
        return ask_user(arguments["question"], arguments.get("options"))
    if tool_name == "add_to_cart":
        return add_to_cart(arguments, session, thread)
    if tool_name == "update_cart":
        return update_cart(arguments, session)
    if tool_name == "checkout_cart":
        return checkout_cart(session, confirm_over_limit=bool(arguments.get("confirm_over_limit")))
    if tool_name == "update_profile":
        return update_profile(arguments, session)
    if tool_name == "save_preferences":
        return save_preferences(arguments, session)
    if tool_name == "clear_preferences":
        return clear_preferences(arguments, session)
    if tool_name == "verify_payment":
        return verify_payment(session, arguments["order_id"], arguments.get("payment_id"))

    logger.error(f"Unknown tool: {tool_name}")
    return {"error": "unknown_tool"}
