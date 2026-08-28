"""Merchant-side aggregation over the order ledger.

Pure reads, no LLM, no side effects — the merchant's numbers should be
reproducible from the ledger alone, and a dashboard refresh must never be able
to change what it's reporting on.

Only **paid** orders count toward revenue. An order sits at `created` from the
moment Razorpay issues it until payment is verified, and counting those would
report money the shop hasn't been given. They're surfaced separately as
`pending_orders` so the gap is visible rather than hidden.

The metric worth pointing at is `revenue_by_buyer`. Attributing revenue to the
buyer *agent* that brought it is only meaningful once several agents can
transact with the same merchant — which is exactly what the auth layer made
possible, and it's the question a merchant in an agentic-commerce market will
actually ask: which AI channels are worth supporting.
"""

import logging
from typing import Any

from ledger import all_orders

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

TOP_PRODUCTS_LIMIT = 5


def _rate(numerator: int, denominator: int) -> float:
    """Percentage, rounded to one place, safe when nothing has sold yet."""
    if not denominator:
        return 0.0
    return round(numerator / denominator * 100, 1)


def merchant_analytics() -> dict[str, Any]:
    """Everything the merchant dashboard renders, computed from the ledger.

    Returns:
        Dict with headline totals, per-buyer-agent attribution, cross-sell
        attach rate, campaign impact and top products. Every rupee figure is
        in whole rupees (never paise), because this is read by humans.
    """
    orders = all_orders()
    paid = [o for o in orders if o.get("status") == "paid"]
    pending = [o for o in orders if o.get("status") != "paid"]

    total_revenue = sum(int(o.get("amount_inr") or 0) for o in paid)
    total_discount = sum(int(o.get("discount_inr") or 0) for o in paid)
    gross_subtotal = sum(int(o.get("subtotal_inr") or o.get("amount_inr") or 0) for o in paid)
    order_count = len(paid)

    # Revenue attributed to the buyer agent that brought it. Sorted by revenue
    # so the channel that matters most reads first.
    by_buyer: dict[str, dict[str, Any]] = {}
    for order in paid:
        buyer_id = order.get("buyer_id") or "unknown"
        bucket = by_buyer.setdefault(
            buyer_id, {"buyer_id": buyer_id, "revenue_inr": 0, "order_count": 0}
        )
        bucket["revenue_inr"] += int(order.get("amount_inr") or 0)
        bucket["order_count"] += 1
    for bucket in by_buyer.values():
        bucket["aov_inr"] = (
            bucket["revenue_inr"] // bucket["order_count"] if bucket["order_count"] else 0
        )
        bucket["revenue_share_pct"] = _rate(bucket["revenue_inr"], total_revenue)
    revenue_by_buyer = sorted(
        by_buyer.values(), key=lambda b: b["revenue_inr"], reverse=True
    )

    # Cross-sell attach rate, measured off the per-line `purpose` flag rather
    # than guessed from line count. An order with two shirts the shopper asked
    # for is not a cross-sell; an order with one shirt plus a T-shirt the agent
    # suggested is. Only the flag can tell those apart.
    attached = [
        o
        for o in paid
        if any((line.get("purpose") == "complement") for line in (o.get("lines") or []))
    ]
    complement_revenue = sum(
        int(line.get("price") or 0) * int(line.get("quantity") or 1)
        for o in paid
        for line in (o.get("lines") or [])
        if line.get("purpose") == "complement"
    )

    campaign_orders = [o for o in paid if o.get("applied_campaign")]
    by_campaign: dict[str, dict[str, Any]] = {}
    for order in campaign_orders:
        campaign = order["applied_campaign"]
        key = campaign.get("id") or "unknown"
        bucket = by_campaign.setdefault(
            key,
            {
                "id": key,
                "kind": campaign.get("kind"),
                "description": campaign.get("description"),
                "order_count": 0,
                "discount_inr": 0,
                "revenue_inr": 0,
            },
        )
        bucket["order_count"] += 1
        bucket["discount_inr"] += int(order.get("discount_inr") or 0)
        bucket["revenue_inr"] += int(order.get("amount_inr") or 0)

    units: dict[str, dict[str, Any]] = {}
    for order in paid:
        for line in order.get("lines") or []:
            pid = line.get("id")
            if not pid:
                continue
            bucket = units.setdefault(
                pid,
                {
                    "product_id": pid,
                    "name": line.get("name") or pid,
                    "units": 0,
                    "revenue_inr": 0,
                },
            )
            quantity = int(line.get("quantity") or 1)
            bucket["units"] += quantity
            bucket["revenue_inr"] += int(line.get("price") or 0) * quantity
    top_products = sorted(units.values(), key=lambda p: p["revenue_inr"], reverse=True)[
        :TOP_PRODUCTS_LIMIT
    ]

    return {
        "total_revenue_inr": total_revenue,
        "order_count": order_count,
        "aov_inr": total_revenue // order_count if order_count else 0,
        "pending_orders": len(pending),
        "pending_value_inr": sum(int(o.get("amount_inr") or 0) for o in pending),
        "revenue_by_buyer": revenue_by_buyer,
        "attach_rate": {
            "orders_with_cross_sell": len(attached),
            "rate_pct": _rate(len(attached), order_count),
            "cross_sell_revenue_inr": complement_revenue,
        },
        "campaign_impact": {
            "orders_with_campaign": len(campaign_orders),
            "rate_pct": _rate(len(campaign_orders), order_count),
            "total_discount_inr": total_discount,
            # What the shop gave up as a share of what it would have charged at
            # list price — the number that says whether the campaigns are a
            # growth lever or just margin leaking away.
            "discount_share_pct": _rate(total_discount, gross_subtotal),
            "revenue_on_campaign_orders_inr": sum(
                int(o.get("amount_inr") or 0) for o in campaign_orders
            ),
            "by_campaign": sorted(
                by_campaign.values(), key=lambda c: c["revenue_inr"], reverse=True
            ),
        },
        "top_products": top_products,
    }
