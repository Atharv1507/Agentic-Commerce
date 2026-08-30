"""Durable record of what this merchant actually sold, and to which buyer agent.

Before this, an order created by `handlers.create_order` left no trace on the
seller side at all — one stdout log line that didn't even carry the amount,
and a copy inside the buyer's own session file. That's fine while exactly one
buyer agent exists and it happens to keep good records. It stops being fine
the moment the merchant is transactable by several: a shop cannot read its own
revenue out of its customers' notebooks, and revenue attributed *per buyer
agent* is the number that only exists in agentic commerce.

The write pattern (serialise, temp file, fsync, atomic `os.replace`, quarantine
an unparseable file on load rather than dying at import) is lifted from
`personal-agent/main.py`, which already had to learn all of it the hard way.

One deliberate difference: **writes here are synchronous.** The session store
hands its write to a daemon thread because a chat reply shouldn't block on
fsync and losing the last turn is survivable — its own docstring says so.
Neither holds for a revenue ledger: a write still queued when the process
exits is simply gone, and an order is created once per checkout, so there is
no hot path worth protecting.
"""

import json
import logging
import os
import threading
import uuid
from datetime import datetime
from pathlib import Path
from typing import Any, Optional

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

LEDGER_FILE = Path("orders.json")

# Guards the tmp-write-then-rename. Writes are synchronous, but FastAPI serves
# requests from a thread pool, so two checkouts can still land at once.
_write_lock = threading.Lock()

_orders: dict[str, dict[str, Any]] = {}


def _load() -> dict[str, dict[str, Any]]:
    """Read the ledger, surviving a file that isn't readable JSON.

    An unparseable ledger is moved aside rather than deleted or ignored in
    place: it is revenue data, so it must stay inspectable, but it must also
    not stop the shop from starting up.
    """
    if not LEDGER_FILE.exists():
        return {}
    try:
        content = LEDGER_FILE.read_text().strip()
        if not content:
            return {}
        loaded = json.loads(content)
    except (json.JSONDecodeError, OSError) as e:
        quarantine = LEDGER_FILE.with_suffix(f".corrupt-{datetime.now():%Y%m%d-%H%M%S}.json")
        try:
            LEDGER_FILE.rename(quarantine)
            logger.error(f"{LEDGER_FILE} is unreadable ({e}); moved to {quarantine}")
        except OSError:
            logger.error(f"{LEDGER_FILE} is unreadable ({e}) and could not be moved aside")
        return {}

    if not isinstance(loaded, dict):
        logger.error(f"{LEDGER_FILE} holds {type(loaded).__name__}, not an object; ignoring it")
        return {}
    return loaded


def _flush() -> None:
    """Write the whole ledger out atomically. Caller already holds the data."""
    try:
        serialised = json.dumps(_orders, indent=2)
    except (TypeError, ValueError) as e:
        # Better to keep the last good ledger than to shred it over one bad value.
        logger.error(f"Ledger is not serialisable ({e}); keeping the previous file")
        return

    tmp = LEDGER_FILE.with_suffix(f".tmp-{uuid.uuid4().hex}")
    try:
        with _write_lock:
            with open(tmp, "w") as f:
                f.write(serialised)
                f.flush()
                os.fsync(f.fileno())
            os.replace(tmp, LEDGER_FILE)
    except OSError as e:
        logger.error(f"Could not write the order ledger: {e}")
        tmp.unlink(missing_ok=True)


_orders = _load()


def record_order(
    order_id: str,
    buyer_id: str,
    subtotal_inr: int,
    discount_inr: int,
    amount_inr: int,
    currency: str,
    lines: list[dict[str, Any]],
    applied_campaign: Optional[dict[str, Any]] = None,
    payment_url: Optional[str] = None,
    payment_link_id: Optional[str] = None,
) -> dict[str, Any]:
    """Persist a newly created order.

    Args:
        order_id: Razorpay's order id, the ledger's primary key.
        buyer_id: Which authenticated buyer agent placed it — the whole basis
            of revenue attribution, so it is required, not optional.
        subtotal_inr: Pre-discount total, kept so campaign impact can be
            measured rather than inferred.
        discount_inr: What the winning campaign took off.
        amount_inr: What Razorpay was actually asked to charge, in rupees.
        currency: Razorpay's currency for the order.
        lines: Per-line records — id, name, price, quantity, size, and
            `purpose` ("primary" or "complement") so cross-sell attach rate is
            a real measurement instead of a guess at "orders with >1 item".
        applied_campaign: The winning campaign, or None.
        payment_url: The hosted payment page for this order, when one was
            created. Recorded so the merchant can re-hand it to a buyer agent
            that lost it, without minting a second link for the same order.
        payment_link_id: Razorpay's id for that link.

    Returns:
        The stored record.
    """
    record = {
        "order_id": order_id,
        "buyer_id": buyer_id,
        "status": "created",
        "subtotal_inr": subtotal_inr,
        "discount_inr": discount_inr,
        "amount_inr": amount_inr,
        "currency": currency,
        "lines": lines,
        "applied_campaign": applied_campaign,
        "created_at": datetime.now().timestamp(),
        "paid_at": None,
        "payment_url": payment_url,
        "payment_link_id": payment_link_id,
        # Which rail settled it, filled in by mark_paid. Distinguishes a sale
        # a headless buyer agent closed on its own from one that needed a
        # browser — the number that says whether agent-to-agent checkout
        # actually works.
        "paid_via": None,
    }
    _orders[order_id] = record
    _flush()
    logger.info(
        f"Ledger: recorded {order_id} for buyer={buyer_id} "
        f"amount=Rs {amount_inr} discount=Rs {discount_inr}"
    )
    return record


def mark_paid(
    order_id: str, payment_id: Optional[str] = None, paid_via: Optional[str] = None
) -> Optional[dict[str, Any]]:
    """Flip an order to paid once payment is verified.

    Merged onto the existing record rather than replacing it — the line items,
    campaign and attribution recorded at creation are what the merchant's
    analytics read, and overwriting them with a bare status would silently
    zero out the revenue this order represents.

    Returns:
        The updated record, or None if this order was never recorded here
        (e.g. created before the ledger existed) — the caller should treat
        that as "nothing to update", not an error.
    """
    record = _orders.get(order_id)
    if not record:
        logger.warning(f"Ledger: asked to mark unknown order {order_id} as paid")
        return None
    if record.get("status") == "paid":
        return record

    record["status"] = "paid"
    record["payment_id"] = payment_id
    record["paid_at"] = datetime.now().timestamp()
    record["paid_via"] = paid_via
    _flush()
    logger.info(f"Ledger: {order_id} marked paid via {paid_via or 'unknown'}")
    return record


def get_order(order_id: str) -> Optional[dict[str, Any]]:
    """One order by id, or None if this shop never recorded it.

    Exists so a settlement path can ask "is this an order of MINE?" before
    acting on an id that arrived from outside. A Razorpay webhook for a
    payment link carries the internal order Razorpay minted for the link as
    well as our own `reference_id`, and only one of those is in this ledger —
    marking the wrong one paid would leave the real sale showing unpaid.

    Returns a copy, so a caller inspecting an order can't mutate the ledger.
    """
    record = _orders.get(order_id)
    return dict(record) if record else None


def pending_orders() -> list[dict[str, Any]]:
    """Orders recorded but not yet settled, newest first.

    The reconciliation pass's work list. Kept here rather than derived by the
    caller so "what counts as unsettled" has exactly one definition.
    """
    return [record for record in all_orders() if record.get("status") != "paid"]


def all_orders() -> list[dict[str, Any]]:
    """Every order the shop has recorded, newest first.

    Returns copies so an analytics pass can't mutate the ledger by accident.
    """
    records = [dict(record) for record in _orders.values()]
    records.sort(key=lambda r: r.get("created_at") or 0, reverse=True)
    return records
