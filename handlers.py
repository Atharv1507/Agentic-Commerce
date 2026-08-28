import os
import logging
from typing import Any, Callable, Optional

import razorpay
from dotenv import load_dotenv

from context import (
    durable_hints,
    expresses_no_preference,
    normalize_gender,
    scrub_constraints,
)
from negotiation import find_products, fetch_facets

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


def checkout_cart(session: dict[str, Any]) -> dict[str, Any]:
    """Create a Razorpay order for the user's current session cart.

    Reads buyer details and cart contents directly from the session so the
    LLM never has to transcribe product IDs or sum amounts itself.

    Args:
        session: Current user session (contains "user" and "cart").

    Returns:
        Dict with order details, or an "error" key describing why checkout
        could not proceed (empty cart, missing buyer info, or a Razorpay
        failure).
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
    amount = sum(item["price"] * item.get("quantity", 1) for item in cart)

    try:
        order = razorpay_client.order.create(
            {
                "amount": amount * 100,
                "currency": "INR",
                "receipt": f"receipt_{'_'.join(product_ids[:3])}",
            }
        )

        logger.info(f"Order created: {order['id']} for products: {product_ids}")
        session["cart"] = []

        return {
            "order_id": order["id"],
            "amount": order["amount"],
            "currency": order["currency"],
            "product_ids": product_ids,
            "buyer": {
                "name": user.get("name", ""),
                "email": user.get("email", ""),
                "phone": user.get("phone", ""),
                "address": user.get("address", ""),
            },
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
        arguments: Any of name/email/phone/address/payment_method/gender.
        session: Current user session (contains "user").

    Returns:
        Dict with the updated user profile.
    """
    user = session.setdefault("user", {})

    for field in ("name", "email", "phone", "address", "payment_method", "gender"):
        value = arguments.get(field)
        if value:
            user[field] = value

    if arguments.get("gender"):
        user["gender_normalized"] = normalize_gender(arguments["gender"])

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


def verify_payment(order_id: str, payment_id: Optional[str] = None) -> dict[str, Any]:
    """Verify payment status for an order.

    Prefers looking up the payment itself (authoritative capture status) over
    the order aggregate, since the caller may pass the two IDs swapped — the
    LLM is handed both an order_id and a payment_id in the same sentence and
    isn't a reliable router between them.

    Args:
        order_id: The Razorpay order ID.
        payment_id: The Razorpay payment ID, if known.

    Returns:
        Dict with payment status.
    """
    try:
        if payment_id:
            payment = razorpay_client.payment.fetch(payment_id)
            logger.info(f"Payment verified for {payment_id}: {payment['status']}")
            return {
                "order_id": payment.get("order_id", order_id),
                "payment_id": payment_id,
                "status": payment["status"],
                "amount": payment["amount"],
            }

        order = razorpay_client.order.fetch(order_id)
        logger.info(f"Payment verified for {order_id}: {order['status']}")
        return {
            "order_id": order["id"],
            "status": order["status"],
            "amount": order["amount"],
        }
    except Exception as e:
        logger.error(f"Payment verification error: {e}")
        return {"error": "verification_failed"}


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
        modal spec, or None) and `profile_dirty` — a flag telling the frontend
        that details or preferences changed mid-chat and Settings should be
        refreshed from the server.
    """
    products: list[dict[str, Any]] = []
    complements: list[dict[str, Any]] = []
    seen_ids: set[str] = set()
    options: Optional[list[str]] = None
    form: Optional[dict[str, Any]] = None
    profile_dirty = False

    for tr in tool_results:
        result = tr.get("result") or {}

        if result.get("profile_updated") or result.get("preferences_updated"):
            profile_dirty = True

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
    2. Gender is filled in from the profile. The shopper's gender is a detail,
       not a preference, and every search should respect it without being told
       to each turn. "Other" resolves to no filter rather than a guess.
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

    if tool_name == "ask_user":
        return ask_user(arguments["question"], arguments.get("options"))
    if tool_name == "checkout_cart":
        return checkout_cart(session)
    if tool_name == "update_profile":
        return update_profile(arguments, session)
    if tool_name == "save_preferences":
        return save_preferences(arguments, session)
    if tool_name == "clear_preferences":
        return clear_preferences(arguments, session)
    if tool_name == "verify_payment":
        return verify_payment(arguments["order_id"], arguments.get("payment_id"))

    logger.error(f"Unknown tool: {tool_name}")
    return {"error": "unknown_tool"}
