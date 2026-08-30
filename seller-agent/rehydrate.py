"""Rebuild the order ledger from Razorpay, so a redeploy can't erase the shop.

`orders.json` is a file on local disk, and `.gitignore` keeps it out of the
repo — correct, it's runtime data. On a host with ephemeral storage that means
every redeploy takes the merchant's entire sales history with it, and the
dashboard comes back reading zero revenue on an account that has sold plenty.

Razorpay has not lost any of it. Every order this merchant ever created is
still there, with its amount, status and creation time. So the ledger does not
have to be the only copy — it can be rebuilt.

What Razorpay stores natively covers revenue, AOV and paid/unpaid. It does not
cover the dimensions that make the merchant dashboard interesting, because none
of them are payments concepts: which *buyer agent* brought the sale, which
campaign applied, what was in the basket, and which lines were cross-sells.
`handlers.build_order_notes` writes exactly those into the order's `notes` at
creation for that reason, and this module reads them back.

Two fidelities, and the difference is reported rather than smoothed over:

**full** — the order carries `notes.ledger`, so buyer attribution, campaign,
discount and lines all come back. Only the product *id* had to survive: name,
brand, colour and image are re-read from `catalog.json`.

**partial** — an order created before notes existed. Recoverable: id, amount,
status, timing, and the product ids that happen to be in Razorpay's `receipt`
field (`receipt_prod_0219_prod_0049` — the first three ids, from
`handlers.create_order`). Not recoverable: buyer agent, campaign, discount, and
any line past the third. Those are filled in as unknown and the record is
flagged, because a rebuilt order that silently claimed `discount_inr: 0` would
make the campaign-impact number a fabrication rather than a gap.

The limits, stated plainly: this is a **backup**, not a second system of
record. Razorpay's `notes` are capped at 15 keys and 256 characters per value,
they are written once at order creation, and nothing here can recover a field
that was never sent. It is worth having because it costs one API field at
checkout and turns total data loss into partial data loss — but a persistent
volume or a real database for `orders.json` is the actual fix for durability,
and this does not replace it.
"""

import logging
import re
from typing import Any, Optional

import ledger
from handlers import LEDGER_NOTES_VERSION, razorpay_client
from rag import get_product_by_id

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Razorpay's page size ceiling for a list call.
PAGE_SIZE = 100

# Refuses to walk forever if the API keeps returning full pages.
MAX_PAGES = 50

# `handlers.create_order` builds `receipt_<id>_<id>_<id>`. The prefix is how an
# order this shop created is told apart from a payment link's internal order
# (whose receipt is our order id) and from hand-made test orders like
# `test_123` and `probe_plink`, which must not be rebuilt as sales.
RECEIPT_PREFIX = "receipt_"

_PRODUCT_ID = re.compile(r"prod_\d+")


def _parse_notes(raw: Any) -> dict[str, str]:
    """Razorpay's `notes`, normalised to a dict.

    An order with no notes comes back as `[]` from the API rather than `{}` —
    a real response shape, not a bug, and one that would raise on `.get`.
    """
    return raw if isinstance(raw, dict) else {}


def _lines_from_notes(notes: dict[str, str]) -> list[dict[str, Any]]:
    """Unpack the lines `handlers._pack_lines` wrote.

    Chunks are read in index order and concatenated. Anything unparseable is
    skipped rather than raising: one malformed line should cost that line, not
    the whole order.
    """
    chunks = [
        notes[key]
        for key in sorted(
            (k for k in notes if k.startswith("lines_")),
            key=lambda k: int(k.removeprefix("lines_") or 0),
        )
    ]

    lines: list[dict[str, Any]] = []
    for chunk in chunks:
        for encoded in str(chunk).split("|"):
            if not encoded.strip():
                continue
            fields = encoded.split(":")
            if not fields[0]:
                continue
            product_id = fields[0]

            def field(index: int) -> Optional[str]:
                value = fields[index] if len(fields) > index else ""
                return value or None

            quantity = field(2)
            price = field(4)
            lines.append(
                {
                    "id": product_id,
                    "size": field(1),
                    "quantity": int(quantity) if quantity and quantity.isdigit() else 1,
                    "purpose": field(3) or "primary",
                    # The price this order was struck at, which may no longer
                    # be the catalogue's price. Kept in preference to it.
                    "price": int(price) if price and price.isdigit() else None,
                }
            )
    return lines


def _lines_from_receipt(receipt: str) -> list[dict[str, Any]]:
    """Best-effort lines for an order created before notes were written.

    All that survives is the product ids in the receipt string, and only the
    first three of them (`create_order` truncates). Repeats become quantity,
    which is how a two-of-the-same-shirt order was encoded. Size and purpose
    are simply gone.
    """
    counts: dict[str, int] = {}
    for product_id in _PRODUCT_ID.findall(receipt or ""):
        counts[product_id] = counts.get(product_id, 0) + 1

    return [
        {
            "id": product_id,
            "size": None,
            "quantity": quantity,
            # Not "primary" — that would assert something. A rebuilt line has
            # no recorded purpose, and attach rate must not count a guess.
            "purpose": None,
            "price": None,
        }
        for product_id, quantity in counts.items()
    ]


def _enrich(line: dict[str, Any]) -> dict[str, Any]:
    """Fill a line's product detail back in from the catalogue.

    This is why only the id had to be stored. Name, brand and colour are
    properties of the product, and the catalogue still has them.

    A product that is no longer stocked (the catalogue has been regenerated at
    least once — older orders reference ids that no longer exist) keeps its id
    and whatever the order recorded, and is marked so a dashboard can say
    "withdrawn product" instead of rendering a blank row.
    """
    product = get_product_by_id(line["id"])
    if not product:
        return {
            **line,
            "name": None,
            "brand": None,
            "type": None,
            "product_missing": True,
        }

    return {
        **line,
        "name": product.get("name"),
        "brand": product.get("brand"),
        # The order's own price wins; the catalogue's is the fallback, since a
        # price can have moved since the sale.
        "price": line.get("price") or product.get("price"),
    }


def _int_or_none(value: Any) -> Optional[int]:
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def _fetch_all_orders() -> list[dict[str, Any]]:
    """Every order on the Razorpay account, oldest page last.

    Paginated with `skip`, stopping on a short page. Razorpay returns newest
    first, which is the order the ledger sorts into anyway.
    """
    orders: list[dict[str, Any]] = []

    for page in range(MAX_PAGES):
        batch = razorpay_client.order.all({"count": PAGE_SIZE, "skip": page * PAGE_SIZE})
        items = batch.get("items") or []
        orders.extend(items)
        if len(items) < PAGE_SIZE:
            break
    else:
        logger.warning(
            f"Stopped paging Razorpay orders at {MAX_PAGES} pages; "
            f"older orders than {len(orders)} were not read"
        )

    return orders


def _link_settlements(orders: list[dict[str, Any]]) -> dict[str, dict[str, Any]]:
    """Map our order id -> the link's internal order, for links that were paid.

    A payment link collects through an order Razorpay mints for itself, so our
    own order stays `created` however completely the link was paid — the trap
    documented in `settlement.py` and README step 9. But that internal order
    carries `notes.order_id` pointing back at ours (set in
    `handlers.create_payment_link`), so paid-ness is recoverable from this one
    listing without a second call per order to the payment link API.
    """
    settled: dict[str, dict[str, Any]] = {}

    for order in orders:
        notes = _parse_notes(order.get("notes"))
        target = notes.get("order_id")
        # Only a link's internal order has a `notes.order_id` naming a
        # *different* order. Our own orders never do.
        if not target or target == order.get("id"):
            continue
        if order.get("status") == "paid":
            settled[target] = order

    return settled


def _rebuild_record(
    order: dict[str, Any], link_settlements: dict[str, dict[str, Any]]
) -> dict[str, Any]:
    """Turn one Razorpay order into a ledger record."""
    order_id = order["id"]
    notes = _parse_notes(order.get("notes"))
    full_fidelity = notes.get("ledger") == LEDGER_NOTES_VERSION

    amount_inr = (_int_or_none(order.get("amount")) or 0) // 100

    if full_fidelity:
        lines = _lines_from_notes(notes)
        subtotal_inr = _int_or_none(notes.get("subtotal_inr")) or amount_inr
        discount_inr = _int_or_none(notes.get("discount_inr")) or 0
        buyer_id = notes.get("buyer_id") or "unknown"
        campaign_id = notes.get("campaign_id") or None
        recorded_line_count = _int_or_none(notes.get("line_count"))
    else:
        lines = _lines_from_receipt(order.get("receipt") or "")
        # No discount was recorded, so none is claimed: subtotal equals what
        # was charged. This understates campaign impact for legacy orders,
        # which is why the record is flagged `partial` — an understated number
        # a reader knows about beats an invented one they don't.
        subtotal_inr = amount_inr
        discount_inr = 0
        buyer_id = "unknown"
        campaign_id = None
        recorded_line_count = None

    settling_link = link_settlements.get(order_id)
    if order.get("status") == "paid":
        status, paid_via = "paid", "checkout"
    elif settling_link:
        status, paid_via = "paid", "payment_link"
    else:
        status, paid_via = "created", None

    record = {
        "order_id": order_id,
        "buyer_id": buyer_id,
        "status": status,
        "subtotal_inr": subtotal_inr,
        "discount_inr": discount_inr,
        "amount_inr": amount_inr,
        "currency": order.get("currency") or "INR",
        "lines": [_enrich(line) for line in lines],
        # Only the id survives in notes, so the campaign's description and
        # exact rupee saving are gone. Naming the id is honest; reconstructing
        # prose the campaign engine would have written is not.
        "applied_campaign": (
            {"id": campaign_id, "discount_inr": discount_inr} if campaign_id else None
        ),
        "created_at": float(_int_or_none(order.get("created_at")) or 0),
        # Razorpay does not expose when the order flipped to paid, only when it
        # was created. Left None rather than back-dated to creation, which
        # would make the gap between order and payment look like zero.
        "paid_at": None,
        "payment_id": None,
        "paid_via": paid_via,
        # So a reader can tell a rebuilt order from one recorded at checkout,
        # and know how much of it to trust.
        "rehydrated": True,
        "fidelity": "full" if full_fidelity else "partial",
    }

    if recorded_line_count is not None and recorded_line_count != len(record["lines"]):
        # The notes were truncated at the key limit. Say so on the record.
        record["lines_truncated"] = {
            "recovered": len(record["lines"]),
            "recorded": recorded_line_count,
        }

    return record


def rebuild_from_razorpay(dry_run: bool = False) -> dict[str, Any]:
    """Rebuild missing ledger entries from the Razorpay account.

    Insert-only, via `ledger.upsert_rehydrated`: an order the ledger already
    holds is never touched, because the record written at checkout is always
    richer than one reconstructed here.

    Args:
        dry_run: Report what would be added without writing anything.

    Returns:
        Dict with `added` (order ids), `skipped_existing`, `skipped_foreign`
        (orders on this Razorpay account that this shop did not create — test
        orders, other integrations, and payment links' internal orders), and
        `fidelity` counts. On failure, an `error` key instead — a rebuild is a
        recovery step, and a Razorpay outage must not stop the shop starting.
    """
    try:
        orders = _fetch_all_orders()
    except Exception as e:
        logger.error(f"Rehydrate: could not read orders from Razorpay: {e}")
        return {"error": "razorpay_unreachable", "message": str(e), "added": []}

    link_settlements = _link_settlements(orders)

    added: list[str] = []
    fidelity = {"full": 0, "partial": 0}
    skipped_existing = 0
    skipped_foreign = 0

    for order in orders:
        order_id = order.get("id")
        if not order_id:
            continue

        notes = _parse_notes(order.get("notes"))
        receipt = order.get("receipt") or ""
        ours = notes.get("ledger") == LEDGER_NOTES_VERSION or receipt.startswith(RECEIPT_PREFIX)
        if not ours:
            skipped_foreign += 1
            continue

        if ledger.get_order(order_id):
            skipped_existing += 1
            continue

        record = _rebuild_record(order, link_settlements)
        if dry_run:
            added.append(order_id)
            fidelity[record["fidelity"]] += 1
            continue

        if ledger.upsert_rehydrated(record):
            added.append(order_id)
            fidelity[record["fidelity"]] += 1

    result = {
        "added": added,
        "added_count": len(added),
        "fidelity": fidelity,
        "skipped_existing": skipped_existing,
        "skipped_foreign": skipped_foreign,
        "razorpay_orders_read": len(orders),
        "dry_run": dry_run,
    }
    logger.info(
        f"Rehydrate{' (dry run)' if dry_run else ''}: read {len(orders)} Razorpay order(s), "
        f"added {len(added)} ({fidelity['full']} full, {fidelity['partial']} partial), "
        f"skipped {skipped_existing} already known and {skipped_foreign} not ours"
    )
    return result


def rebuild_if_empty() -> dict[str, Any]:
    """Rebuild on startup, but only when the ledger is actually gone.

    This is the redeploy case: a container comes up with no `orders.json` on a
    Razorpay account that has history, which means the file was lost rather
    than that nothing ever sold. A ledger with even one order in it is left
    alone — a rebuild there would only be able to add orders the shop already
    knows about or degrade nothing, and startup is not the place to spend a
    page of API calls proving it.
    """
    if not ledger.is_empty():
        return {"skipped": "ledger_not_empty", "added": []}

    logger.info("Rehydrate: ledger is empty — rebuilding from Razorpay")
    return rebuild_from_razorpay()
