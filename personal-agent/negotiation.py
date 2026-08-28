"""Constraint-checked negotiation between the Personal Agent and the Seller Agent.

The Personal Agent used to forward one query to the Seller Agent and relay
whatever came back. That let plainly wrong results reach the shopper — ₹1,239
watches for a ₹10,000 budget, the wrong colour, the same product twice.

This module makes the exchange a bounded loop instead: brief the seller, verify
every returned product against the shopper's constraints *in code*, and if too
few survive, tell the seller exactly what was wrong and ask again. Verification
is deterministic, so no amount of confident seller prose can pass off a result
that breaks a constraint.
"""

import logging
import re
from typing import Any, Callable, Optional

import httpx

from config import SELLER_AGENT_URL, SELLER_AUTH_HEADERS

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# How many times the Personal Agent may push back before it gives up and
# reports the shortfall honestly. Three is enough to walk the relaxation ladder
# below without leaving the shopper waiting indefinitely.
MAX_SELLER_ROUNDS = 3
# A cross-sell is a nice-to-have. Grinding through the full ladder for one adds
# latency to every search for something the shopper didn't even ask about.
MAX_COMPLEMENT_ROUNDS = 2
DEFAULT_MIN_RESULTS = 3

# How much of the budget each round is willing to accept, as a ratio of the
# stated budget. Round 1 asks for what the shopper actually wants; later rounds
# widen the floor rather than the ceiling, because "cheaper than asked" is the
# failure mode we're fixing.
BUDGET_FLOOR_RATIOS = [0.80, 0.55, 0.30]
PREMIUM_FLOOR_RATIOS = [0.85, 0.70, 0.55]
# Only a shopper who signalled flexibility gets shown anything over budget.
FLEXIBLE_CEILING_RATIOS = [1.10, 1.20, 1.35]
# How far the floor of an explicitly chosen price band eases per round. The
# ceiling never moves: the shopper picked that band deliberately.
BAND_FLOOR_RELAXATION = [1.0, 0.85, 0.7]

# Colour families, so "grey" accepts charcoal and slate. Deliberately a local
# copy rather than an import from the seller service — these are two separate
# processes and the Personal Agent must be able to check colour without
# trusting the seller to have applied it.
COLOR_GROUPS = {
    "grey": {"grey", "gray", "charcoal", "slate", "graphite", "gunmetal", "steel"},
    "silver": {"silver", "chrome", "metallic", "platinum"},
    "black": {"black", "jet", "onyx", "ebony"},
    "white": {"white", "ivory", "cream", "offwhite"},
    "blue": {"blue", "navy", "teal", "turquoise", "cobalt", "indigo", "denim"},
    "green": {"green", "olive", "mint", "sage", "emerald"},
    "red": {"red", "maroon", "burgundy", "wine", "crimson", "rust"},
    "pink": {"pink", "rose", "blush", "fuchsia", "magenta"},
    "brown": {"brown", "tan", "beige", "khaki", "camel", "coffee", "taupe"},
    "yellow": {"yellow", "mustard", "gold", "golden", "lemon"},
    "purple": {"purple", "lavender", "violet", "lilac", "mauve"},
    "orange": {"orange", "peach", "coral", "apricot"},
}
# A grey request should accept silver before it accepts yellow.
ADJACENT_COLORS = {
    ("grey", "silver"),
    ("grey", "black"),
    ("brown", "yellow"),
    ("pink", "red"),
    ("purple", "pink"),
}

_TOKEN_TO_COLOR = {t: c for c, tokens in COLOR_GROUPS.items() for t in tokens}
_ADJACENCY: dict[str, set[str]] = {}
for _a, _b in ADJACENT_COLORS:
    _ADJACENCY.setdefault(_a, set()).add(_b)
    _ADJACENCY.setdefault(_b, set()).add(_a)

# Cap on how many product IDs we remember per shopper. Enough to stop repeats
# across a realistic session without the session file growing without bound.
SEEN_PRODUCTS_MEMORY = 60

# Cap on how many FULL product records we keep per conversation. `last_shown`
# only holds id/name/brand, which is enough to talk about a card but not enough
# to put one in the cart — a cart line needs the price, the stocked sizes and
# the image. Kept smaller than the ID memory because these records are fat.
SHOWN_CATALOG_MEMORY = 24


# Words that say nothing about what kind of product something is, so they must
# not be what makes a complement look like a duplicate of the primary item.
_GENERIC_TOKENS = frozenset(
    """a an the and or for with in on of to me my i want need looking show find
    some something please under below above around near about like similar more
    less very really just that this it is are be men women unisex kids
    premium budget cheap expensive nice good best new classic casual formal""".split()
)


# Folded before word-splitting so a hyphen never fractures "T-Shirt" into "t"
# + "shirt" — the plain regex below treats "-" as a separator, which made
# every T-shirt's name contain the literal token "shirt" and get flagged as
# "the same kind of item" as a Shirt search. That collision defeated this
# store's only legitimate cross-sell pairing (shirt <-> T-shirt) every time.
# Mirrors context.py's COMPOUND_PATTERNS, kept local for the same reason
# COLOR_GROUPS is: this tokenizer must not depend on the seller process.
_TSHIRT_PATTERN = re.compile(r"\bt[\s\-]?shirts?\b")


def _tokens(text: str) -> set[str]:
    folded = _TSHIRT_PATTERN.sub(" tshirt ", (text or "").lower())
    return {
        t
        for t in re.findall(r"[a-z]+", folded)
        if len(t) > 2 and t not in _GENERIC_TOKENS
    }


def _canonical_color(value: str) -> Optional[str]:
    for token in re.findall(r"[a-z]+", (value or "").lower()):
        if token in _TOKEN_TO_COLOR:
            return _TOKEN_TO_COLOR[token]
    return None


def forget_seller_session(session_id: str) -> None:
    """Drop the seller's scratch history for a finished negotiation.

    Each search gets its own seller session (see `find_products`) so nothing
    leaks between searches; without this the seller would accumulate one dead
    history per search for the lifetime of the process.
    """
    try:
        with httpx.Client(timeout=5.0) as client:
            client.delete(
                f"{SELLER_AGENT_URL}/session/{session_id}", headers=SELLER_AUTH_HEADERS
            )
    except Exception:
        # Best effort — the seller prunes its own sessions as a backstop.
        pass


def message_seller(text: str, session_id: str) -> dict[str, Any]:
    """Send a free-text brief to the Seller Agent.

    Args:
        text: Message to send to the Seller Agent.
        session_id: Session ID scoping the seller's memory to ONE negotiation,
            so its rounds share context but separate searches never do.

    Returns:
        Dict with the Seller Agent's response and tool results.
    """
    try:
        with httpx.Client(timeout=60.0) as client:
            response = client.post(
                f"{SELLER_AGENT_URL}/message",
                json={"session_id": session_id, "text": text},
                headers=SELLER_AUTH_HEADERS,
            )
            response.raise_for_status()
            result = response.json()
            logger.info(f"Seller Agent response: {result.get('response', '')[:100]}...")
            return result
    except httpx.TimeoutException:
        logger.error("Seller Agent timeout")
        return {"response": "Seller is unavailable. Please try again shortly.", "tool_results": [], "error": True}
    except Exception as e:
        logger.error(f"Seller Agent error: {e}")
        return {"response": "Seller is unavailable. Please try again shortly.", "tool_results": [], "error": True}


def fetch_facets(
    query: str, gender: Optional[str] = None, full: bool = False
) -> dict[str, Any]:
    """Ask the Seller Agent which choices actually exist for a product type.

    Args:
        query: The product type, e.g. "shirt".
        gender: Optional gender filter.
        full: Ask for the complete, untruncated facet lists instead of a
            form-sized subset. Use when answering the shopper directly.

    Returns:
        Facet dict, or an empty dict if the seller can't be reached — the
        caller should degrade to asking nothing rather than to guessing.
    """
    try:
        with httpx.Client(timeout=15.0) as client:
            response = client.post(
                f"{SELLER_AGENT_URL}/facets",
                json={"query": query, "gender": gender, "full": full},
                headers=SELLER_AUTH_HEADERS,
            )
            response.raise_for_status()
            return response.json()
    except Exception as e:
        logger.error(f"Facet lookup failed: {e}")
        return {}


def check_sizes(product_ids: list[str], size: Optional[str]) -> dict[str, Any]:
    """Ask the seller, exactly and without an LLM, whether these can ship in `size`.

    Used at checkout. Search already filters by size, but a cart can be built
    from cards that were shown before the shopper's size was known, or added
    from the sidebar — so the last word on "can this actually be sent" is taken
    here rather than assumed.

    Returns:
        The seller's stock report, or `{}` when it can't be reached. An empty
        dict means "unknown", and the caller lets the order through: blocking
        checkout because a health check failed is the worse error.
    """
    if not product_ids or not size:
        return {}
    try:
        with httpx.Client(timeout=15.0) as client:
            response = client.post(
                f"{SELLER_AGENT_URL}/stock",
                json={"product_ids": product_ids, "size": size},
                headers=SELLER_AUTH_HEADERS,
            )
            response.raise_for_status()
            return response.json()
    except Exception as e:
        logger.error(f"Stock check failed: {e}")
        return {}


def create_seller_order(
    product_ids: list[str],
    buyer_name: str,
    buyer_address: str,
    buyer_email: str,
    buyer_phone: str,
    sizes: Optional[dict[str, str]] = None,
    buyer_size: Optional[str] = None,
    purposes: Optional[dict[str, str]] = None,
    buyer_context: Optional[dict[str, Any]] = None,
) -> dict[str, Any]:
    """Ask the merchant to create the Razorpay order for this cart.

    The merchant owns its own Razorpay account, so it is the only party that
    can legitimately create an order against it — this agent no longer holds
    merchant payment credentials at all.

    Unlike `check_sizes`, an unreachable seller here is fatal rather than
    something to shrug off: a failed stock pre-check just means "unknown", but
    a failed order means no order exists, and pretending otherwise would show
    the shopper a checkout that never happened. Returned as a structured error
    for `checkout_cart` to explain.

    Returns:
        The merchant's order dict, or `{"error": "seller_unreachable"}`.
    """
    payload: dict[str, Any] = {
        "product_ids": product_ids,
        "buyer_name": buyer_name,
        "buyer_address": buyer_address,
        "buyer_email": buyer_email,
        "buyer_phone": buyer_phone,
    }
    if sizes:
        payload["sizes"] = sizes
    if buyer_size:
        payload["buyer_size"] = buyer_size
    if purposes:
        payload["purposes"] = purposes
    if buyer_context:
        payload["buyer_context"] = buyer_context

    try:
        # Longer than the read-only calls: this one waits on Razorpay's own API
        # behind the merchant, and abandoning it early could leave an order
        # created at the merchant that this agent never learns about.
        with httpx.Client(timeout=45.0) as client:
            response = client.post(
                f"{SELLER_AGENT_URL}/order",
                json=payload,
                headers=SELLER_AUTH_HEADERS,
            )
            response.raise_for_status()
            return response.json()
    except Exception as e:
        logger.error(f"Seller order creation failed: {e}")
        return {
            "error": "seller_unreachable",
            "message": (
                "The shop's system could not be reached, so no order was created and "
                "nothing has been charged. Tell the shopper plainly and suggest trying "
                "again in a moment. Their cart is unchanged."
            ),
        }


def verify_seller_payment(order_id: str, payment_id: Optional[str] = None) -> dict[str, Any]:
    """Ask the merchant to confirm a payment against Razorpay.

    Read-only on the merchant's side, so a retry is harmless.

    Returns:
        The merchant's verification result, or `{"error": "seller_unreachable"}`
        — deliberately distinct from the merchant's own
        `{"error": "verification_failed"}`, since "we couldn't ask" and
        "Razorpay said no" call for different things to be said to a shopper.
    """
    try:
        with httpx.Client(timeout=30.0) as client:
            response = client.post(
                f"{SELLER_AGENT_URL}/payment/verify",
                json={"order_id": order_id, "payment_id": payment_id},
                headers=SELLER_AUTH_HEADERS,
            )
            response.raise_for_status()
            return response.json()
    except Exception as e:
        logger.error(f"Seller payment verification failed: {e}")
        return {
            "error": "seller_unreachable",
            "message": (
                "Could not reach the shop to confirm the payment. Do not tell the "
                "shopper the payment failed — it may well have succeeded. Say the "
                "confirmation is delayed and their receipt will follow."
            ),
        }


def _offers_from_reply(reply: dict[str, Any]) -> list[dict[str, Any]]:
    """Pull live merchant offers out of a seller reply's tool results.

    The merchant's own prose is discarded (see `_products_from_reply`), so an
    offer only reaches the shopper as structured data that this agent's model
    then words for itself — the same route product cards already take. Only
    offers the merchant marked as actually applying are surfaced: an `almost`
    offer is a fact about what *would* qualify, and letting it through here
    would invite the model to describe an unearned discount as earned.
    """
    offers: list[dict[str, Any]] = []
    seen: set[str] = set()
    for tr in reply.get("tool_results") or []:
        if tr.get("tool") != "evaluate_offers":
            continue
        for offer in (tr.get("result") or {}).get("offers", []):
            offer_id = offer.get("id")
            if not offer.get("applies") or not offer_id or offer_id in seen:
                continue
            seen.add(offer_id)
            offers.append(offer)
    return offers


def _products_from_reply(reply: dict[str, Any]) -> list[dict[str, Any]]:
    """Pull the product list out of a seller reply's search tool results."""
    products = []
    seen = set()
    for tr in reply.get("tool_results") or []:
        if tr.get("tool") != "search_catalog":
            continue
        for product in (tr.get("result") or {}).get("products", []):
            pid = product.get("id")
            if pid and pid not in seen:
                seen.add(pid)
                products.append(product)
    return products


def compute_band(constraints: dict[str, Any], round_no: int) -> dict[str, Any]:
    """Work out the acceptable price window and colour strictness for a round.

    Args:
        constraints: The shopper's constraint object.
        round_no: 1-based negotiation round.

    Returns:
        Dict with min/max/target price (any may be None) and require_color.
    """
    index = min(round_no, MAX_SELLER_ROUNDS) - 1
    budget = constraints.get("budget")
    explicit_min = constraints.get("budget_min")
    explicit_max = constraints.get("budget_max")
    premium = bool(constraints.get("premium"))
    flexible = bool(constraints.get("budget_flexible"))

    band: dict[str, Any] = {
        "min": None,
        "max": None,
        "target": None,
        # Colour is only mandatory on the opening round. After that it stays a
        # ranking preference — better to show a near-miss than nothing at all.
        "require_color": index == 0,
    }

    # An explicit range (usually a price band the shopper picked) is taken at
    # face value — squeezing "₹749 to ₹1,224" into a single target and then
    # deriving a floor from it turns the floor into a ceiling.
    if explicit_min or explicit_max:
        band["max"] = explicit_max
        band["min"] = int(explicit_min * BAND_FLOOR_RELAXATION[index]) if explicit_min else None
        if explicit_min and explicit_max:
            band["target"] = (explicit_min + explicit_max) // 2
        else:
            band["target"] = explicit_max or explicit_min
        return band

    if not budget:
        return band

    if constraints.get("purpose") == "complement":
        # A cross-sell is a "spend up to this" ask, not a "spend around this"
        # one. Applying the usual floor made every complement search fail: a
        # ₹500 accessory budget became a ₹400-₹500 window, which almost nothing
        # lands in.
        band["max"] = budget
        band["target"] = int(budget * 0.6)
        return band

    floor_ratios = PREMIUM_FLOOR_RATIOS if premium else BUDGET_FLOOR_RATIOS
    ceiling_ratio = FLEXIBLE_CEILING_RATIOS[index] if flexible else 1.0

    band["min"] = int(budget * floor_ratios[index])
    band["max"] = int(budget * ceiling_ratio)
    # Aim at the budget itself when the shopper is stretching for the right
    # piece; a plain "under X" aims just below the ceiling.
    band["target"] = int(budget if (flexible or premium) else budget * 0.9)
    return band


def evaluate_product(
    product: dict[str, Any],
    constraints: dict[str, Any],
    band: dict[str, Any],
    same_type_tokens: Optional[set[str]] = None,
) -> list[str]:
    """Check one product against the constraints.

    Args:
        product: Product dict from the seller.
        constraints: The shopper's constraint object.
        band: Output of `compute_band` for the current round.
        same_type_tokens: Words describing the primary item. On a cross-sell
            pass, a "complement" sharing one of these is just another item of
            the same kind — a second watch is not an accessory for the first.

    Returns:
        List of violated-constraint tags. Empty means the product is acceptable.
    """
    problems = []
    price = product.get("price") or 0

    if same_type_tokens and _tokens(product.get("name", "")) & same_type_tokens:
        problems.append("same_as_primary")

    if band["max"] and price > band["max"]:
        problems.append("over_budget")
    if band["min"] and price < band["min"]:
        problems.append("under_budget")

    wanted_gender = (constraints.get("gender") or "").strip().lower()
    actual_gender = (product.get("gender") or "").strip().lower()
    if wanted_gender and actual_gender not in (wanted_gender, "unisex"):
        problems.append("wrong_gender")

    wanted_size = constraints.get("size")
    if wanted_size:
        # Absent `available_sizes` means the seller didn't say, and an unproven
        # miss is not a miss — the checkout probe is the backstop for that.
        stocked = product.get("available_sizes")
        if stocked is not None and wanted_size not in stocked:
            problems.append("size_unavailable")

    wanted_colors = [c for c in (constraints.get("colors") or []) if c]
    if wanted_colors and band["require_color"]:
        actual = _canonical_color(product.get("color", ""))
        wanted = {_canonical_color(c) or c.lower() for c in wanted_colors}
        if not actual or (actual not in wanted and not (_ADJACENCY.get(actual, set()) & wanted)):
            problems.append("wrong_color")

    return problems


def _describe_rejections(
    rejected: list[tuple[dict[str, Any], list[str]]], band: dict[str, Any]
) -> str:
    """Turn rejection tags into a correction the Seller Agent can act on."""
    if not rejected:
        return "Nothing usable came back at all."

    tally: dict[str, list[dict[str, Any]]] = {}
    for product, problems in rejected:
        for problem in problems:
            tally.setdefault(problem, []).append(product)

    def count(n: int) -> str:
        return "1 was" if n == 1 else f"{n} were"

    notes = []
    if "under_budget" in tally:
        prices = sorted(p["price"] for p in tally["under_budget"])
        notes.append(
            f"{count(len(prices))} far too cheap (₹{prices[0]:,}-₹{prices[-1]:,}); "
            f"this buyer is shopping at ₹{band['min']:,}+, not the bargain shelf"
        )
    if "over_budget" in tally:
        prices = sorted(p["price"] for p in tally["over_budget"])
        notes.append(f"{count(len(prices))} over budget (up to ₹{prices[-1]:,})")
    if "wrong_color" in tally:
        colors = sorted({p.get("color", "?") for p in tally["wrong_color"]})
        notes.append(f"{count(len(tally['wrong_color']))} the wrong colour ({', '.join(colors)})")
    if "wrong_gender" in tally:
        notes.append(f"{count(len(tally['wrong_gender']))} for the wrong gender")
    if "size_unavailable" in tally:
        notes.append(
            f"{count(len(tally['size_unavailable']))} not stocked in the buyer's size — "
            f"pass `size` to search_catalog so unwearable items never come back"
        )

    return "; ".join(notes) + "."


def build_brief(
    constraints: dict[str, Any],
    band: dict[str, Any],
    exclude_ids: set[str],
    round_no: int,
    feedback: Optional[str],
) -> str:
    """Compose the natural-language brief sent to the Seller Agent.

    Constraints are spelled out explicitly rather than left implicit in prose,
    because the seller has to map them onto search_catalog arguments.
    """
    lines = []

    if round_no == 1:
        lines.append(f"Buyer request: {constraints['query']}")
    else:
        lines.append(
            f"Round {round_no}. Your last set did not work: {feedback} "
            f"Search again with the corrected constraints below — do not repeat the same call."
        )
        lines.append(f"Buyer request: {constraints['query']}")

    if band["target"]:
        # A complement has no price floor, so describe it as a ceiling rather
        # than a window and leave min_price out of the seller's call entirely.
        if band["min"]:
            lines.append(
                f"Budget: aim for around ₹{band['target']:,}. "
                f"Acceptable range is ₹{band['min']:,} to ₹{band['max']:,} — "
                f"set target_price={band['target']}, min_price={band['min']}, max_price={band['max']}."
            )
        else:
            lines.append(
                f"Budget: anything up to ₹{band['max']:,}, ideally around "
                f"₹{band['target']:,} — set target_price={band['target']}, "
                f"max_price={band['max']}. Do not set min_price."
            )
        if constraints.get("premium"):
            lines.append("The buyer explicitly wants something premium, so do not go low.")
        if constraints.get("budget_flexible"):
            lines.append("The buyer said their budget is flexible for the right piece.")

    if constraints.get("colors"):
        strictness = "required" if band["require_color"] else "strongly preferred"
        lines.append(f"Colour ({strictness}): {', '.join(constraints['colors'])}.")

    if constraints.get("materials"):
        lines.append(
            f"Fabric (preferred, not mandatory): {', '.join(constraints['materials'])} — "
            f"pass it as `materials`. If the catalogue has none, say so rather than "
            f"pretending a different fabric matches."
        )

    if constraints.get("brands"):
        lines.append(
            f"Brand affinity: {', '.join(constraints['brands'])} "
            f"(or comparable brands at that quality level)."
        )

    if constraints.get("gender"):
        lines.append(f"Gender: {constraints['gender']} (Unisex is fine too).")

    if constraints.get("size"):
        lines.append(
            f"Size: {constraints['size']} — REQUIRED. Pass size=\"{constraints['size']}\" to "
            f"search_catalog. Only return products with stock in that size; the buyer "
            f"cannot wear anything else, so an item that is out of stock in "
            f"{constraints['size']} is not a result."
        )

    if exclude_ids:
        capped = list(exclude_ids)[:40]
        lines.append(
            f"Already seen or already rejected — pass these as exclude_ids and do not "
            f"return them again: {', '.join(capped)}."
        )

    lines.append(f"Return up to {max(6, constraints.get('min_results', DEFAULT_MIN_RESULTS) * 2)} candidates.")
    return "\n".join(lines)


def find_products(
    constraints: dict[str, Any],
    session: dict[str, Any],
    thread: dict[str, Any],
    emit: Optional[Callable[[str, dict[str, Any]], None]] = None,
) -> dict[str, Any]:
    """Negotiate with the Seller Agent until the constraints are met or rounds run out.

    Args:
        constraints: query, plus any of budget, budget_flexible, premium,
            colors, brands, gender, min_results, purpose.
        session: The shopper's account-level session (profile, durable prefs).
        thread: The active conversation's state. Already-seen products and the
            "what are we shopping for" subject live here, not on the account,
            so a second chat starts clean instead of inheriting the first
            chat's exclusions and constraints.
        emit: Optional progress callback, called as emit(stage, payload).

    Returns:
        Dict with the accepted `products`, a `rounds` trace, and — when the
        constraints could not be fully met — a `shortfall` the agent must
        disclose to the shopper rather than paper over.
    """
    def progress(stage: str, **payload: Any) -> None:
        if emit:
            emit(stage, payload)

    query = constraints.get("query") or ""
    purpose = constraints.get("purpose") or "primary"
    min_results = int(constraints.get("min_results") or DEFAULT_MIN_RESULTS)
    # One seller session per search. The seller needs history across the rounds
    # of a single negotiation ("round 2, your last set didn't work"), and must
    # have none at all across searches — a shared session is why a trousers
    # request could still come back talking about the linen shirts it failed to
    # find two searches ago.
    thread["search_seq"] = int(thread.get("search_seq") or 0) + 1
    seller_session_id = (
        f"{session.get('user', {}).get('email') or 'anon'}"
        f":{thread.get('id') or 'default'}:{thread['search_seq']}"
    )

    # Remember what the shopper is actually buying, so the follow-up cross-sell
    # pass can reject "complements" that are really the same product type.
    if purpose == "primary":
        thread["last_primary_tokens"] = sorted(_tokens(query))
        same_type_tokens = None
    else:
        same_type_tokens = set(thread.get("last_primary_tokens") or [])

    previously_seen = set(thread.get("seen_product_ids") or [])
    # Hiding everything already shown is what stops the agent re-offering the
    # same three watches every turn — but it must not become a dead end when
    # the shopper deliberately refers back to something, so the caller can opt
    # out for that turn.
    # Rejects join this set as we go, so a later round can't hand back
    # something an earlier round already ruled out.
    exclude: set[str] = set() if constraints.get("include_seen") else set(previously_seen)

    accepted: dict[str, dict[str, Any]] = {}
    rounds: list[dict[str, Any]] = []
    # Kept across rounds so an empty result can say WHY it's empty. "Nothing
    # matched" and "everything matched but none of it comes in your size" are
    # different answers, and only the second one is worth the shopper's time.
    size_rejected: list[dict[str, Any]] = []
    feedback: Optional[str] = None
    seller_unreachable = False
    # Live campaigns the merchant volunteered during this search, if any.
    merchant_offers: list[dict[str, Any]] = []

    max_rounds = MAX_COMPLEMENT_ROUNDS if purpose == "complement" else MAX_SELLER_ROUNDS

    for round_no in range(1, max_rounds + 1):
        band = compute_band(constraints, round_no)

        progress(
            "seller_round",
            round=round_no,
            max_rounds=max_rounds,
            query=query,
            band=band,
        )

        reply = message_seller(build_brief(constraints, band, exclude, round_no, feedback), seller_session_id)
        if reply.get("error"):
            seller_unreachable = True
            break

        offered = _products_from_reply(reply)
        # Kept per round and overwritten rather than accumulated: the merchant
        # re-evaluates offers against whatever basket the latest round is
        # about, so an offer from an earlier, wider brief may no longer hold.
        # The last round's answer is the only current one.
        round_offers = _offers_from_reply(reply)
        if round_offers:
            merchant_offers = round_offers
        progress("evaluating", round=round_no, offered=len(offered))

        fresh_accepted = 0
        rejected: list[tuple[dict[str, Any], list[str]]] = []
        for product in offered:
            pid = product.get("id")
            if not pid or pid in accepted or pid in exclude:
                continue
            problems = evaluate_product(product, constraints, band, same_type_tokens)
            if problems:
                rejected.append((product, problems))
                if "size_unavailable" in problems:
                    size_rejected.append(
                        {
                            "name": product.get("name"),
                            "available_sizes": product.get("available_sizes") or [],
                        }
                    )
            else:
                accepted[pid] = product
                fresh_accepted += 1

        # Everything the seller has shown this round is off the table next
        # round, accepted or not.
        exclude.update(p["id"] for p in offered if p.get("id"))

        rounds.append(
            {
                "round": round_no,
                "band": band,
                "offered": len(offered),
                "accepted": fresh_accepted,
                "rejected": len(rejected),
            }
        )
        logger.info(
            f"Round {round_no}: seller offered {len(offered)}, "
            f"{fresh_accepted} met constraints, {len(rejected)} rejected"
        )

        if len(accepted) >= min_results:
            break

        feedback = _describe_rejections(rejected, band)
        if round_no < max_rounds:
            progress(
                "retry",
                round=round_no + 1,
                have=len(accepted),
                need=min_results,
                reason=feedback,
            )

    forget_seller_session(seller_session_id)

    # Best-scoring first, with a couple of extras beyond the minimum so the
    # shopper has room to choose. When a fabric was asked for, genuine fabric
    # matches sort above near-misses regardless of score: a shopper who said
    # "linen" would rather see the linen shirt third-best on every other signal
    # than a higher-scoring polyester one.
    if constraints.get("materials"):
        ranked = sorted(
            accepted.values(),
            key=lambda p: (not p.get("matches_material"), -(p.get("relevance") or 0)),
        )[: min_results + 2]
    else:
        ranked = sorted(accepted.values(), key=lambda p: -(p.get("relevance") or 0))[: min_results + 2]

    # Later rounds deliberately loosen the ask, so some of what survived may
    # not meet what the shopper originally said. Re-check each result against
    # the ROUND 1 constraints and mark it, otherwise the agent describes a
    # relaxed set using the shopper's original words — "here are black shirts
    # above ₹749" over a pink one at ₹684.
    strict_band = compute_band(constraints, 1)
    relaxed_tags: set[str] = set()
    for product in ranked:
        misses = evaluate_product(product, constraints, strict_band, same_type_tokens)
        product["exact_match"] = not misses
        relaxed_tags.update(misses)

    if ranked:
        remembered = list(previously_seen | {p["id"] for p in ranked})
        thread["seen_product_ids"] = remembered[-SEEN_PRODUCTS_MEMORY:]
        # Names and IDs of what's currently on screen, so a follow-up about
        # "the second one" or "the blue one" can be resolved to a product ID
        # without the model having to scroll its own history for it.
        thread["last_shown"] = [
            {"id": p["id"], "name": p.get("name"), "brand": p.get("brand")} for p in ranked
        ]
        # Full records for the same products, so add_to_cart can build a real
        # cart line from an ID the shopper pointed at instead of the agent
        # inventing a price or a size. Re-inserted on every appearance so the
        # eviction below drops the oldest-shown, not the oldest-first-seen.
        catalog = thread.setdefault("shown_catalog", {})
        for p in ranked:
            # Remember whether this was shown as a cross-sell or as what the
            # shopper actually asked for. `add_to_cart` builds a cart line by
            # copying this record, so the marker rides along to the cart and
            # then to the order — which is the only way the merchant can
            # measure a real attach rate later. Without it, a complement is
            # indistinguishable from a primary line by the time it's sold.
            p["purpose"] = purpose
            catalog.pop(p["id"], None)
            catalog[p["id"]] = p
        for stale in list(catalog)[:-SHOWN_CATALOG_MEMORY]:
            del catalog[stale]

    result: dict[str, Any] = {
        "products": ranked,
        # Stated explicitly because the model otherwise counts what it saw
        # during the search rather than what actually reached the shopper.
        "shown_count": len(ranked),
        "purpose": purpose,
        "rounds": rounds,
        "rounds_used": len(rounds),
        "constraints_applied": {
            k: constraints.get(k)
            for k in (
                "budget", "budget_min", "budget_max", "budget_flexible",
                "premium", "colors", "materials", "brands", "gender",
            )
            if constraints.get(k)
        },
    }

    exact = sum(1 for p in ranked if p.get("exact_match"))
    result["exact_match_count"] = exact

    # Merchant campaigns, passed through as the merchant stated them. This
    # agent does not compute, adjust or re-word the saving — it is the
    # merchant's money and the merchant's promise, and the discount is applied
    # merchant-side at order time whether or not it gets mentioned here.
    if merchant_offers:
        result["offers"] = merchant_offers
        result["offers_note"] = (
            "The shop is running these offers on this selection. Mention them naturally, "
            "using the shop's own wording for the saving. Do not invent, combine or "
            "recalculate any figure — only one discount applies per order, and the shop "
            "applies it at checkout regardless of what you say here."
        )

    if relaxed_tags:
        readable = {
            "under_budget": "cheaper than asked",
            "over_budget": "above the budget",
            "wrong_color": "not the requested colour",
            "wrong_gender": "a different gender",
            "same_as_primary": "the same kind of item",
            "size_unavailable": "not available in your size",
        }
        loosened = ", ".join(sorted(readable.get(t, t) for t in relaxed_tags))
        result["relaxation_note"] = (
            f"Only {exact} of {len(ranked)} match exactly what was asked for; the rest are "
            f"{loosened}. Say this plainly — describe the set as the closest available, "
            f"and do NOT restate the original constraint as though every result meets it."
        )

    # Fabric is a preference, so a non-match still gets shown — but the shopper
    # has to be told, otherwise cotton silently passes as the linen they asked
    # for.
    wanted_materials = constraints.get("materials") or []
    if wanted_materials and ranked:
        fabric_matches = sum(1 for p in ranked if p.get("matches_material"))
        result["material_match_count"] = fabric_matches

        if not fabric_matches:
            result["material_shortfall"] = (
                f"None of these are {', '.join(wanted_materials)} — the catalogue has no "
                f"{wanted_materials[0]} in this category. Say so up front; do not imply they match."
            )
        elif fabric_matches < len(ranked):
            # The dangerous case, because it looks like a success. Some results
            # match and some don't, and calling the whole set "linen shirts" is
            # a plain untruth about the ones that aren't.
            result["material_note"] = (
                f"Only {fabric_matches} of these {len(ranked)} are actually "
                f"{', '.join(wanted_materials)}; the rest are the closest alternatives in "
                f"other fabrics. Say that explicitly — give the number that really match "
                f"and never describe the whole set as {wanted_materials[0]}."
            )

    if purpose == "complement":
        # A cross-sell coming back empty just means nothing here pairs with the
        # main item. That's a non-event — say nothing rather than apologising.
        if not ranked:
            result["shortfall"] = (
                "No genuine complement exists in the catalogue. Do not mention "
                "cross-sells at all in your reply."
            )
        progress("resolved", found=len(ranked), rounds=len(rounds), purpose=purpose)
        return result

    if seller_unreachable:
        result["shortfall"] = "The seller could not be reached. Tell the shopper to try again shortly."
    elif not ranked and size_rejected:
        # The blocker is the one constraint that can't be negotiated away.
        others = sorted({s for item in size_rejected for s in item["available_sizes"]})
        result["size_shortfall"] = (
            f"{len(size_rejected)} product(s) otherwise fit, but NONE of them are available "
            f"in size {constraints['size']}. Tell the shopper exactly that — this specific "
            f"item is not available in their size — rather than saying nothing matched. "
            + (
                f"These items do exist in {', '.join(others)}, so offer to look again in a "
                f"different size if they'd wear one."
                if others
                else "They are sold out across the board."
            )
        )
        result["shortfall"] = result["size_shortfall"]
    elif not ranked:
        result["shortfall"] = (
            f"After {len(rounds)} rounds the seller had nothing matching these constraints. "
            f"Tell the shopper plainly that nothing fits, say which constraint is the blocker, "
            f"and offer to widen it — do NOT show products that break it."
        )
    elif len(ranked) < min_results:
        reason = (
            f" {len(size_rejected)} more were right but not stocked in size "
            f"{constraints['size']}."
            if size_rejected
            else ""
        )
        result["shortfall"] = (
            f"Only {len(ranked)} of the {min_results} requested options actually fit."
            f"{reason} Show these and mention the selection at this spec is limited."
        )

    progress("resolved", found=len(ranked), rounds=len(rounds), purpose=result["purpose"])
    return result
