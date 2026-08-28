import os
import logging
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


def verify_payment(order_id: str, payment_id: Optional[str] = None) -> dict[str, Any]:
    """Confirm with Razorpay whether an order has actually been paid.

    Prefers looking up the payment itself over the order aggregate, since the
    caller may pass the two ids swapped — a buyer agent is handed both in the
    same breath and is not a reliable router between them.

    Read-only against Razorpay: it never captures, refunds or moves money, so
    it is safe to call more than once. Idempotency of the *consequences* of a
    confirmation is the caller's business, not this function's.

    Args:
        order_id: The Razorpay order id.
        payment_id: The Razorpay payment id, when known.

    Returns:
        Dict with the payment status, or `{"error": "verification_failed"}`.
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
                "amount_inr": payment["amount"] // 100,
                "amount_note": f"Quote Rs {payment['amount'] // 100:,} — `amount` is in paise.",
            }

        order = razorpay_client.order.fetch(order_id)
        logger.info(f"Payment verified for {order_id}: {order['status']}")
        return {
            "order_id": order["id"],
            "status": order["status"],
            "amount": order["amount"],
            "amount_inr": order["amount"] // 100,
            "amount_note": f"Quote Rs {order['amount'] // 100:,} — `amount` is in paise.",
        }
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
