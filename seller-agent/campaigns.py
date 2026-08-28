"""The merchant's revenue policy: which offers exist and when they apply.

This is deliberately a rules engine and not an LLM call. A discount is a
money action — it has to be the same every time for the same cart, it has to
be explainable after the fact, and it must not be something a buyer agent can
talk the shop into by phrasing a brief persuasively. Same reasoning that
already keeps `create_order` and `/stock` LLM-free on this service.

The seller's LLM still decides whether and how to *mention* an offer
(`evaluate_offers` is a tool it may call mid-negotiation). It never decides
what an offer *is* — that lives here, and `create_order` applies it whether
the model brought it up or not.

Two invariants worth stating because they are the ones that would hurt:

- **Discounts never stack.** Only the single best-value campaign is applied.
  Stacking a win-back offer onto a threshold discount onto a bundle price is
  how a demo ends up giving away 40% and how a real shop loses money on an
  order it thought was profitable.
- **A discount is capped** at `MAX_DISCOUNT_RATIO` of the subtotal, as a
  backstop against a future campaign being mis-specified.
"""

import logging
from typing import Any, Optional

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Hard ceiling on any single order's discount, regardless of what the
# qualifying campaign says. A rule that would exceed this is clamped, not
# honoured — a mis-typed percentage should cost the shop a rounding error,
# not the order.
MAX_DISCOUNT_RATIO = 0.25

# Spend that unlocks the threshold discount, and how close a cart has to be
# before it's worth telling the buyer what they'd need to add. The "almost"
# case is the actual upsell lever: it converts a ₹2,700 cart into a ₹3,000
# one far more often than a discount nobody knows about.
THRESHOLD_INR = 3000
THRESHOLD_RATE = 0.10
ALMOST_THRESHOLD_INR = 2200

# Flat saving for buying across both categories the shop stocks. Flat rather
# than a percentage so the bundle reads as a concrete "save ₹300" rather than
# a number the buyer has to compute.
BUNDLE_SAVING_INR = 300

# A shopper who has never ordered here gets a small welcome; one who has
# ordered but not recently gets a larger nudge. The win-back is bigger on
# purpose — re-activating a lapsed buyer is worth more than shaving margin off
# someone already mid-purchase.
FIRST_ORDER_RATE = 0.05
WIN_BACK_RATE = 0.15
WIN_BACK_DAYS = 30


def product_type(product: dict[str, Any]) -> str:
    """Classify a catalogue product as a t-shirt or a shirt.

    Reads `tags`, which the catalogue builds with "tshirt" or "shirt" already
    folded into a single token — checking the display name instead would mean
    re-solving the "T-Shirt" / "T shirt" / "Tshirt" spelling problem that
    `negotiation.py` has its own regex for.
    """
    tags = product.get("tags") or []
    return "tshirt" if "tshirt" in tags else "shirt"


def _subtotal(products: list[dict[str, Any]]) -> int:
    return sum(int(p.get("price") or 0) for p in products)


def _clamp(discount: int, subtotal: int) -> int:
    """Keep a discount inside the shop's own safety rail."""
    ceiling = int(subtotal * MAX_DISCOUNT_RATIO)
    if discount > ceiling:
        logger.warning(
            f"Campaign discount {discount} exceeded the {MAX_DISCOUNT_RATIO:.0%} "
            f"cap on a Rs {subtotal} subtotal; clamped to {ceiling}"
        )
        return ceiling
    return max(discount, 0)


def evaluate_campaigns(
    products: list[dict[str, Any]],
    buyer_context: Optional[dict[str, Any]] = None,
) -> list[dict[str, Any]]:
    """Every campaign that currently applies to this basket, best value first.

    Pure: reads its arguments, touches no global state, creates no order and
    charges nothing. `create_order` calls it to price an order; the
    `evaluate_offers` tool calls it to tell the seller's LLM what it may
    mention. Both get the same answer for the same basket, which is the point.

    Args:
        products: Full catalogue records for the basket being priced. One
            entry per unit, matching how `create_order` counts.
        buyer_context: What the buyer's agent reports about this shopper —
            `order_count`, `days_since_last_order`, `lifetime_spend_inr`. Self
            reported and unverified (see the README note), so it may only ever
            unlock a *discount*, never a price increase or an entitlement.

    Returns:
        A list of offer dicts. Each carries `id`, `kind`, `description` (said
        to a human as-is), `discount_inr` (0 for a suggestion), and `applies`
        — False for an "almost" offer, which describes what the buyer would
        need to do rather than something they've already earned.
    """
    buyer_context = buyer_context or {}
    subtotal = _subtotal(products)
    offers: list[dict[str, Any]] = []

    if subtotal <= 0:
        return offers

    types = {product_type(p) for p in products}

    # 1. Threshold discount — the plain "spend more, save more" lever.
    if subtotal >= THRESHOLD_INR:
        discount = _clamp(int(subtotal * THRESHOLD_RATE), subtotal)
        offers.append(
            {
                "id": "threshold_10",
                "kind": "threshold_discount",
                "applies": True,
                "discount_inr": discount,
                "description": (
                    f"{THRESHOLD_RATE:.0%} off orders over Rs {THRESHOLD_INR:,} — "
                    f"saves Rs {discount:,} on this Rs {subtotal:,} order."
                ),
            }
        )
    elif subtotal >= ALMOST_THRESHOLD_INR:
        # Not a discount yet. Reported so the seller's LLM can tell the buyer
        # what would unlock it — stated as a gap, never as an earned saving.
        shortfall = THRESHOLD_INR - subtotal
        offers.append(
            {
                "id": "threshold_10",
                "kind": "threshold_discount",
                "applies": False,
                "discount_inr": 0,
                "shortfall_inr": shortfall,
                "description": (
                    f"Rs {shortfall:,} more would take this order over "
                    f"Rs {THRESHOLD_INR:,} and unlock {THRESHOLD_RATE:.0%} off."
                ),
            }
        )

    # 2. Bundle — rewards buying across both categories the shop stocks.
    if {"shirt", "tshirt"} <= types:
        discount = _clamp(BUNDLE_SAVING_INR, subtotal)
        offers.append(
            {
                "id": "shirt_tshirt_bundle",
                "kind": "bundle",
                "applies": True,
                "discount_inr": discount,
                "description": (
                    f"Shirt + T-shirt bundle — Rs {discount:,} off for taking one of each."
                ),
            }
        )
    elif len(types) == 1:
        # 3. Cross-sell — a suggestion, not a price change. The only honest
        # pairing in a shop that sells exactly two categories.
        missing = "T-shirt" if "tshirt" not in types else "shirt"
        offers.append(
            {
                "id": "cross_sell_pair",
                "kind": "cross_sell",
                "applies": True,
                "discount_inr": 0,
                "suggest_type": "tshirt" if missing == "T-shirt" else "shirt",
                "description": (
                    f"Adding a {missing} would qualify this order for the "
                    f"Rs {BUNDLE_SAVING_INR:,} shirt + T-shirt bundle."
                ),
            }
        )

    # 4. Lifecycle — first order, or a win-back for someone who has lapsed.
    order_count = buyer_context.get("order_count")
    days_since = buyer_context.get("days_since_last_order")

    if order_count == 0:
        discount = _clamp(int(subtotal * FIRST_ORDER_RATE), subtotal)
        offers.append(
            {
                "id": "first_order_welcome",
                "kind": "lifecycle",
                "applies": True,
                "discount_inr": discount,
                "description": (
                    f"First-order welcome — {FIRST_ORDER_RATE:.0%} off, "
                    f"saves Rs {discount:,}."
                ),
            }
        )
    elif (
        isinstance(order_count, int)
        and order_count > 0
        and isinstance(days_since, (int, float))
        and days_since >= WIN_BACK_DAYS
    ):
        discount = _clamp(int(subtotal * WIN_BACK_RATE), subtotal)
        offers.append(
            {
                "id": "win_back",
                "kind": "lifecycle",
                "applies": True,
                "discount_inr": discount,
                "description": (
                    f"Welcome back — {WIN_BACK_RATE:.0%} off after "
                    f"{int(days_since)} days away, saves Rs {discount:,}."
                ),
            }
        )

    # Best value first, so `best_offer` is just the head of the list and the
    # seller's LLM sees the most compelling offer before the also-rans.
    offers.sort(key=lambda o: (o.get("applies", False), o.get("discount_inr", 0)), reverse=True)
    return offers


def price_basket(
    products: list[dict[str, Any]],
    buyer_context: Optional[dict[str, Any]] = None,
) -> dict[str, Any]:
    """Final price for a basket, plus the one campaign that produced it.

    The single source of truth for what an order costs. `create_order` calls
    this instead of summing prices itself, so the amount charged and the
    amount explained can never disagree.

    Discounts do not stack: the best-value applicable campaign wins outright.

    Returns:
        Dict with `subtotal_inr`, `discount_inr`, `total_inr`, and
        `applied_campaign` (None when nothing qualified) carrying the id,
        kind and human-readable description of the winning campaign.
    """
    subtotal = _subtotal(products)
    offers = evaluate_campaigns(products, buyer_context)

    discounting = [o for o in offers if o.get("applies") and o.get("discount_inr", 0) > 0]
    best = max(discounting, key=lambda o: o["discount_inr"], default=None)

    discount = best["discount_inr"] if best else 0
    # Guard against a campaign ever driving an order to zero or negative: the
    # cap above makes this unreachable today, but a future campaign shouldn't
    # be able to produce a free order by accident.
    discount = min(discount, max(subtotal - 1, 0))

    return {
        "subtotal_inr": subtotal,
        "discount_inr": discount,
        "total_inr": subtotal - discount,
        "applied_campaign": (
            {
                "id": best["id"],
                "kind": best["kind"],
                "description": best["description"],
                "discount_inr": discount,
            }
            if best and discount > 0
            else None
        ),
    }
