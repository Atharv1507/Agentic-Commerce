import os
import logging
import time
from typing import Any, Optional

import razorpay
from dotenv import load_dotenv

from campaigns import evaluate_campaigns, price_basket, product_type
from rag import available_sizes, search_catalog, get_product_by_id, price_range
from vocab import SIZES, canonical_size

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

load_dotenv()

razorpay_client = razorpay.Client(
    auth=(os.getenv("RAZORPAY_KEY_ID"), os.getenv("RAZORPAY_KEY_SECRET"))
)


# How long a buyer agent has to get the order paid through its payment link.
# Long enough for a human to be asked and to act; short enough that a stale
# link isn't a live charge sitting around forever. Razorpay requires at least
# 15 minutes.
PAYMENT_LINK_TTL_SECONDS = 24 * 60 * 60


def create_payment_link(
    order: dict[str, Any],
    buyer_name: str,
    buyer_email: str,
    buyer_phone: str,
    unit_count: int,
) -> dict[str, Any]:
    """Create a hosted payment page for an order, and return its URL.

    Why this exists: `razorpay_client.order.create` produces an id that can
    only be paid by something running Razorpay's *browser* SDK — which needs a
    DOM and a human to enter card details. A headless buyer agent has neither,
    so until now the `purchase` capability this merchant advertises stopped one
    step short of a payment any third party could actually complete. A payment
    link closes that: the merchant hands back a URL, and whoever actually holds
    the money (the agent's own user, typically) opens it. The merchant's
    key_secret never leaves this service and the buyer agent still receives no
    payment credential of any kind.

    `reference_id` is set to our order id so the link can be found from the
    order later — see `verify_payment`, which needs it because a link's payment
    does NOT attach to the order created above. Razorpay generates the link its
    own internal order, so `order.fetch` on our id stays "created" forever even
    after the link is paid.

    Args:
        order: The Razorpay order this link should collect for.
        buyer_name: Shopper name, prefilled on the hosted page.
        buyer_email: Shopper email, prefilled.
        buyer_phone: Shopper phone, prefilled.
        unit_count: How many units the order covers, for the description.

    Returns:
        Dict with `payment_url` and `payment_link_id`, or `{}` if the link
        could not be created. Never raises: an order that exists without a link
        is still payable in a browser, so a link failure must not take the
        whole checkout down with it.
    """
    try:
        link = razorpay_client.payment_link.create(
            {
                "amount": order["amount"],
                "currency": order["currency"],
                "accept_partial": False,
                # Ties the link back to the order the ledger knows about.
                "reference_id": order["id"],
                "description": f"Order {order['id']} — {unit_count} item(s)",
                "customer": {
                    "name": buyer_name or "",
                    "email": buyer_email or "",
                    "contact": buyer_phone or "",
                },
                # The buyer agent decides how to deliver the link to its user.
                # The merchant spamming the shopper directly is not its call.
                "notify": {"sms": False, "email": False},
                "reminder_enable": False,
                "expire_by": int(time.time()) + PAYMENT_LINK_TTL_SECONDS,
                "notes": {"order_id": order["id"]},
            }
        )
        logger.info(f"Payment link {link['id']} created for {order['id']}: {link['short_url']}")
        return {"payment_url": link["short_url"], "payment_link_id": link["id"]}
    except Exception as e:
        logger.error(f"Could not create a payment link for {order['id']}: {e}")
        return {}


def check_stock(product_id: str, size: Optional[str] = None) -> dict[str, Any]:
    """Report real per-size availability for a product.

    Args:
        product_id: The product ID to check.
        size: Optional size to answer about specifically. Any spelling works
            ("large", "L", "size l").

    Returns:
        Dict with the per-size counts and, when a size was named, whether that
        particular size can be bought. `in_stock` always answers the question
        that was actually asked — for a size-specific check it is about that
        size, not about the product in general, because "yes it's in stock"
        followed by "sorry, not in your size" is the failure this replaces.
    """
    product = get_product_by_id(product_id)
    if not product:
        logger.warning(f"Product not found: {product_id}")
        return {"error": "product_not_found"}

    counts = product["sizes"]
    in_size = available_sizes(product)
    total = sum(counts.values())

    result: dict[str, Any] = {
        "product_id": product_id,
        "name": product["name"],
        "sizes": counts,
        "available_sizes": in_size,
        "total_units": total,
        "in_stock": bool(in_size),
    }

    wanted = canonical_size(size)
    if size and not wanted:
        result["size_note"] = (
            f"'{size}' is not a size this shop uses. Sizes are {', '.join(SIZES)}."
        )
        return result

    if wanted:
        count = counts.get(wanted, 0)
        result["requested_size"] = wanted
        result["requested_size_count"] = count
        result["in_stock"] = count > 0
        if count == 0:
            # Spelled out as an instruction, not just data: an LLM handed
            # `{"L": 0}` alongside `in_stock` for the product as a whole has
            # repeatedly read it as a yes.
            result["size_unavailable"] = (
                f"This product is NOT available in {wanted}. "
                + (
                    f"It is in stock in {', '.join(in_size)}."
                    if in_size
                    else "It is sold out in every size."
                )
                + " Say so plainly — do not offer it in a size the buyer did not ask for "
                  "as though it were what they wanted, and do not create an order for it."
            )

    logger.info(f"Stock check {product_id} size={wanted or 'any'}: {result['in_stock']}")
    return result


def evaluate_offers(
    product_ids: Optional[list[str]] = None,
    cart_total_inr: Optional[int] = None,
    buyer_context: Optional[dict[str, Any]] = None,
) -> dict[str, Any]:
    """Report which of the shop's live campaigns apply to a prospective basket.

    Read-only and deterministic — it prices nothing and charges nothing. This
    exists so the seller's own model can find out what the shop is willing to
    offer *during* a negotiation, and decide whether it's worth mentioning.
    The discount itself is applied by `create_order` regardless, so this tool
    influences the conversation, never the price.

    Args:
        product_ids: The products under discussion. Repeat an id per unit.
        cart_total_inr: A stand-in total, for when the buyer's agent has stated
            a basket value without naming products yet. Ignored when
            `product_ids` is given, since real products are strictly better
            information (they carry type, which drives the bundle rule).
        buyer_context: Self-reported shopper history from the buyer's agent —
            order_count, days_since_last_order. Unverified, so it can only
            ever unlock a discount.

    Returns:
        Dict with `offers` (best first), `best_offer`, and a `note` telling the
        model plainly what it may and may not say.
    """
    basket: list[dict[str, Any]] = []
    if product_ids:
        for pid in product_ids:
            product = get_product_by_id(pid)
            if product:
                basket.append(product)
    elif cart_total_inr:
        # No product identities, so the type-based rules (bundle, cross-sell)
        # can't fire — only the value- and lifecycle-based ones. Represented as
        # a single synthetic line so `evaluate_campaigns` stays unaware of the
        # distinction.
        basket = [{"price": int(cart_total_inr), "tags": []}]

    if not basket:
        return {
            "offers": [],
            "best_offer": None,
            "note": (
                "No basket to evaluate. Name the products under discussion "
                "(or a cart total) before quoting any offer."
            ),
        }

    offers = evaluate_campaigns(basket, buyer_context)
    applicable = [o for o in offers if o.get("applies")]
    best = next((o for o in applicable if o.get("discount_inr", 0) > 0), None)

    return {
        "offers": offers,
        "best_offer": best,
        "note": (
            "These are the only offers you may mention. Discounts do not stack "
            "— exactly one (the best) is applied at order time, so quote that "
            "one, not the sum. An offer with applies=false has NOT been earned: "
            "describe it as what would unlock it, never as a saving already won."
        ),
    }


def create_order(
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
    """Create a Razorpay order for multiple products, in the buyer's sizes.

    Size is validated here and not only at search time. Between a shopper
    seeing a product and paying for it, the size they want can be the one thing
    that doesn't hold — and taking money for a garment that cannot ship is a
    worse failure than refusing the order.

    Pricing is delegated to `campaigns.price_basket` rather than summed here,
    so the amount charged and the amount explained come from one place and
    cannot drift apart.

    Args:
        product_ids: List of product IDs to order. Repeat an id per unit.
        buyer_name: Name of the buyer.
        buyer_address: Delivery address.
        buyer_email: Email of the buyer.
        buyer_phone: Phone of the buyer.
        sizes: Optional per-product size, keyed by product ID.
        buyer_size: Fallback size for any product `sizes` doesn't cover —
            normally the buyer's usual size from their profile.
        purposes: Optional per-product "primary" / "complement", keyed by
            product ID. Recorded on each line so the merchant can measure a
            real cross-sell attach rate later; a line with no entry is
            treated as primary.
        buyer_context: Self-reported shopper history, used only to test
            lifecycle campaign conditions.

    Returns:
        Dict with order details, or an error naming the product and the sizes
        it can actually be had in.
    """
    products = []
    sizes = sizes or {}
    purposes = purposes or {}
    fallback_size = canonical_size(buyer_size)
    ordered_sizes: dict[str, str] = {}

    # A size string this shop can't parse must be refused, not dropped.
    # `canonical_size` returns None both for "not supplied" and for "XXXL" /
    # "banana", and the two used to be indistinguishable here — so a buyer
    # agent sending a size that doesn't exist got an order created with no
    # size validated at all, which is precisely the "took money for a garment
    # that can't ship" failure the rest of this function exists to prevent.
    # Cheap to get wrong from outside the building, so it's checked explicitly
    # now that any buyer agent can call this.
    unparseable = [
        value
        for value in ([buyer_size] if buyer_size else []) + list(sizes.values())
        if value and not canonical_size(value)
    ]
    if unparseable:
        return {
            "error": "invalid_size",
            "invalid_sizes": unparseable,
            "valid_sizes": list(SIZES),
            "message": (
                f"{', '.join(repr(s) for s in unparseable)} is not a size this shop "
                f"stocks. Valid sizes are {', '.join(SIZES)}. Ask the buyer to pick one "
                f"of those — do not retry with the same value."
            ),
        }

    for pid in product_ids:
        product = get_product_by_id(pid)
        if not product:
            logger.warning(f"Product not found for order: {pid}")
            return {"error": "product_not_found", "product_id": pid}

        wanted = canonical_size(sizes.get(pid)) or fallback_size
        stock = check_stock(pid, wanted)
        if stock.get("error"):
            return {"error": "product_not_found", "product_id": pid}
        if not stock.get("in_stock"):
            logger.warning(f"Out of stock: {pid} size={wanted or 'any'}")
            return {
                "error": "size_unavailable" if wanted else "out_of_stock",
                "product_id": pid,
                "product_name": product["name"],
                "requested_size": wanted,
                "available_sizes": stock.get("available_sizes", []),
                "message": (
                    f"{product['name']} is not available in {wanted}. "
                    + (
                        f"Available sizes: {', '.join(stock['available_sizes'])}."
                        if stock.get("available_sizes")
                        else "It is sold out entirely."
                    )
                    if wanted
                    else f"{product['name']} is sold out in every size."
                ),
            }

        if wanted:
            ordered_sizes[pid] = wanted
        products.append(product)

    pricing = price_basket(products, buyer_context)
    total_amount = pricing["total_inr"]

    # One entry per unit ordered, collapsed to one line per (product, size) so
    # a ledger reader sees "2 x M" rather than the same row twice.
    lines: list[dict[str, Any]] = []
    line_index: dict[tuple[str, Optional[str]], dict[str, Any]] = {}
    for product in products:
        pid = product["id"]
        key = (pid, ordered_sizes.get(pid))
        if key in line_index:
            line_index[key]["quantity"] += 1
            continue
        line = {
            "id": pid,
            "name": product.get("name"),
            "brand": product.get("brand"),
            "price": product.get("price"),
            "size": ordered_sizes.get(pid),
            "quantity": 1,
            "type": product_type(product),
            "purpose": purposes.get(pid, "primary"),
        }
        line_index[key] = line
        lines.append(line)

    try:
        order = razorpay_client.order.create(
            {
                "amount": total_amount * 100,
                "currency": "INR",
                "receipt": f"receipt_{'_'.join(product_ids[:3])}",
            }
        )

        logger.info(
            f"Order created: {order['id']} for {len(product_ids)} unit(s), "
            f"subtotal=Rs {pricing['subtotal_inr']} discount=Rs {pricing['discount_inr']} "
            f"charged=Rs {total_amount}"
        )
        # A second rail to the same order, for a caller that has no browser.
        # Additive: the order id above is unchanged and still the primary key
        # everywhere, so the existing browser checkout is untouched.
        link = create_payment_link(
            order, buyer_name, buyer_email, buyer_phone, len(product_ids)
        )

        result = {
            "order_id": order["id"],
            # Razorpay works in paise and the payment SDK is handed `amount`
            # verbatim, so it has to stay in paise. Anything read aloud must
            # come from `amount_inr` — quoting the paise figure as rupees is a
            # bug this codebase has already shipped once.
            "amount": order["amount"],
            "amount_inr": order["amount"] // 100,
            "amount_note": (
                f"Quote Rs {order['amount'] // 100:,} to the buyer. `amount` is in paise "
                f"for the payment SDK — never state it as rupees."
            ),
            "currency": order["currency"],
            "subtotal_inr": pricing["subtotal_inr"],
            "discount_inr": pricing["discount_inr"],
            "applied_campaign": pricing["applied_campaign"],
            "products": products,
            "sizes": ordered_sizes,
            "lines": lines,
            "buyer": {
                "name": buyer_name,
                "email": buyer_email,
                "phone": buyer_phone,
                "address": buyer_address,
            },
            # Present unless Razorpay refused the link. A buyer agent with no
            # browser pays here; one driving a browser can ignore it, or fall
            # back to it when the checkout SDK won't open.
            **link,
            "payment_note": (
                "Two ways to pay this order, both settling the same `order_id`: open "
                "`payment_url` (works anywhere, no SDK or credentials needed), or pass "
                "`order_id` to Razorpay's browser Checkout with the merchant's public "
                "key_id. Either way, confirm with POST /payment/verify before treating "
                "the order as paid."
                if link
                else "This order has no payment link; it must be paid through Razorpay's "
                "browser Checkout using `order_id`."
            ),
        }
        if pricing["applied_campaign"]:
            # Surfaced as `message` so the buyer's audit trail picks it up
            # through the explanation-key path it already has, with no extra
            # wiring on that side.
            result["message"] = (
                f"Order created for Rs {total_amount:,} "
                f"(Rs {pricing['subtotal_inr']:,} less Rs {pricing['discount_inr']:,}). "
                f"{pricing['applied_campaign']['description']}"
            )
        return result
    except Exception as e:
        logger.error(f"Razorpay error: {e}")
        return {"error": "order_creation_failed"}


PAID_STATUSES = ("captured", "paid")


def _split_ids(*candidates: Optional[str]) -> tuple[Optional[str], Optional[str]]:
    """Sort a jumble of Razorpay ids into (order id, payment id) by prefix.

    Razorpay ids are prefixed — `order_`, `pay_`, `plink_` — so which is which
    is knowable rather than guessable. The previous version trusted the
    argument positions and merely commented that a buyer agent "is not a
    reliable router between them"; this stops it from mattering.

    Returns:
        (order_id, payment_id), either of which may be None.
    """
    order_id = payment_id = None
    for value in candidates:
        if not value:
            continue
        if value.startswith("pay_"):
            payment_id = payment_id or value
        elif value.startswith("order_"):
            order_id = order_id or value
    return order_id, payment_id


def _payment_link_status(order_id: str) -> dict[str, Any]:
    """Ask whether the payment link for an order has been paid.

    Needed because a payment link collects through an order Razorpay creates
    *itself*: the link's payment is attached to that internal order, never to
    the one this merchant created. So `order.fetch(our_id)` reports "created"
    forever no matter how completely the link was paid, and a buyer agent that
    paid the only way it could would be told its money never arrived.

    Args:
        order_id: The merchant's order id, used as the link's `reference_id`.

    Returns:
        The link's status and its payment id when paid, or `{}` when there is
        no link for this order (or the lookup failed — an unknown answer must
        not read as an unpaid one).
    """
    try:
        found = razorpay_client.payment_link.all({"reference_id": order_id})
    except Exception as e:
        logger.error(f"Payment link lookup failed for {order_id}: {e}")
        return {}

    links = found.get("payment_links") or []
    if not links:
        return {}

    # Newest first: an expired or cancelled link may have been reissued.
    links.sort(key=lambda l: l.get("created_at") or 0, reverse=True)
    paid = next((l for l in links if l.get("status") == "paid"), None)
    link = paid or links[0]

    payments = link.get("payments") or []
    return {
        "status": "paid" if link.get("status") == "paid" else link.get("status"),
        "payment_id": next((p.get("payment_id") for p in payments if p.get("payment_id")), None),
        "payment_link_id": link.get("id"),
        "amount_paid": link.get("amount_paid"),
    }


def verify_payment(order_id: str, payment_id: Optional[str] = None) -> dict[str, Any]:
    """Confirm with Razorpay whether an order has actually been paid.

    Checks both rails a buyer can pay on, in cost order: the payment itself if
    an id was given, then the order, then the order's payment link. The link is
    checked last because it costs an extra API call and only matters for a
    caller with no browser — but it must be checked, or a headless buyer agent
    can never be told its payment succeeded.

    Read-only against Razorpay: it never captures, refunds or moves money, so
    it is safe to call more than once. Idempotency of the *consequences* of a
    confirmation is the caller's business, not this function's.

    Args:
        order_id: The Razorpay order id. May be passed swapped with payment_id;
            both are re-sorted by prefix.
        payment_id: The Razorpay payment id, when known.

    Returns:
        Dict with the payment status. `order_id` is always the order the caller
        asked about — the one in this merchant's ledger — never the internal
        order a payment link collected through, which would settle nothing.
        Includes `paid_via` so the merchant can see which rail was used.
        `{"error": "verification_failed"}` if Razorpay could not be reached.
    """
    resolved_order, resolved_payment = _split_ids(order_id, payment_id)
    # An id with no recognised prefix (an older caller, or a test fixture)
    # keeps its positional meaning rather than being dropped. One that IS
    # recognised is never re-used in the other slot — that's the whole point of
    # sorting them, and treating a `pay_` id as the order to settle would put
    # the wrong key in the ledger.
    if not resolved_order and order_id and not order_id.startswith("pay_"):
        resolved_order = order_id
    if not resolved_payment and payment_id and not payment_id.startswith("order_"):
        resolved_payment = payment_id

    try:
        if resolved_payment:
            payment = razorpay_client.payment.fetch(resolved_payment)
            logger.info(f"Payment verified for {resolved_payment}: {payment['status']}")
            return {
                # The caller's order id wins when we have one: a link payment's
                # own order_id is Razorpay's internal one, and settling the
                # ledger against that would mark nothing paid.
                "order_id": resolved_order or payment.get("order_id"),
                "payment_id": resolved_payment,
                "status": payment["status"],
                "amount": payment["amount"],
                "amount_inr": payment["amount"] // 100,
                "amount_note": f"Quote Rs {payment['amount'] // 100:,} — `amount` is in paise.",
                "paid_via": (
                    "checkout" if payment.get("order_id") == resolved_order else "payment_link"
                ),
            }

        order = razorpay_client.order.fetch(resolved_order)
        result = {
            "order_id": order["id"],
            "status": order["status"],
            "amount": order["amount"],
            "amount_inr": order["amount"] // 100,
            "amount_note": f"Quote Rs {order['amount'] // 100:,} — `amount` is in paise.",
        }
        if result["status"] in PAID_STATUSES:
            # Only claimed once something is actually paid — naming a rail on an
            # unpaid order reads as a settlement that hasn't happened.
            result["paid_via"] = "checkout"
            logger.info(f"Payment verified for {resolved_order}: {result['status']}")
            return result

        # Not paid in a browser. It may well have been paid on the link.
        link = _payment_link_status(order["id"])
        if link.get("status") in PAID_STATUSES:
            logger.info(
                f"Payment verified for {order['id']} via payment link "
                f"{link.get('payment_link_id')}: paid"
            )
            return {**result, **link, "order_id": order["id"], "paid_via": "payment_link"}

        logger.info(
            f"Payment not verified for {order['id']}: order={result['status']} "
            f"link={link.get('status') or 'none'}"
        )
        if link:
            result["payment_link_status"] = link.get("status")
        return result
    except Exception as e:
        logger.error(f"Payment verification error: {e}")
        return {"error": "verification_failed"}


def execute_tool(
    tool_name: str,
    arguments: dict[str, Any],
    buyer_context: Optional[dict[str, Any]] = None,
) -> dict[str, Any]:
    """Execute a tool by name with given arguments.

    Args:
        tool_name: Name of the tool to execute.
        arguments: Tool arguments, as chosen by the model.
        buyer_context: Shopper history supplied by the buyer's agent on the
            request. Passed out-of-band rather than as a tool argument on
            purpose — it is a fact about the caller, not a decision the model
            gets to make, so the model must not be able to invent or inflate
            it to unlock a better lifecycle offer.

    Returns:
        Tool execution result.
    """
    logger.info(f"Executing tool: {tool_name}")

    if tool_name == "search_catalog":
        products = search_catalog(
            arguments["query"],
            top_k=arguments.get("top_k") or 5,
            max_price=arguments.get("max_price"),
            min_price=arguments.get("min_price"),
            target_price=arguments.get("target_price"),
            gender=arguments.get("gender"),
            colors=arguments.get("colors"),
            materials=arguments.get("materials"),
            brands=arguments.get("brands"),
            size=arguments.get("size"),
            exclude_ids=arguments.get("exclude_ids"),
        )
        # Echoing the constraints back lets the Personal Agent verify what was
        # actually applied rather than trusting that its brief survived the
        # trip through this agent's tool-call reasoning.
        return {
            "products": products,
            "applied_constraints": {
                k: arguments.get(k)
                for k in ("max_price", "min_price", "target_price", "gender", "colors", "materials", "brands", "size")
                if arguments.get(k)
            },
        }
    elif tool_name == "price_range":
        return price_range(arguments["query"], gender=arguments.get("gender"))
    elif tool_name == "check_stock":
        return check_stock(arguments["product_id"], arguments.get("size"))
    elif tool_name == "evaluate_offers":
        return evaluate_offers(
            product_ids=arguments.get("product_ids"),
            cart_total_inr=arguments.get("cart_total_inr"),
            buyer_context=buyer_context,
        )
    elif tool_name == "create_order":
        return create_order(
            arguments["product_ids"],
            arguments["buyer_name"],
            arguments["buyer_address"],
            arguments["buyer_email"],
            arguments["buyer_phone"],
            sizes=arguments.get("sizes"),
            buyer_size=arguments.get("buyer_size"),
            purposes=arguments.get("purposes"),
            buyer_context=buyer_context,
        )

    logger.error(f"Unknown tool: {tool_name}")
    return {"error": "unknown_tool"}
