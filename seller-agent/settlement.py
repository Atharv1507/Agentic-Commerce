"""How the shop finds out it was paid, without depending on the buyer agent.

Until this module existed there was exactly one way an order in `orders.json`
could move from `created` to `paid`: a buyer agent choosing to call
`POST /payment/verify` afterwards. That is the wrong party to depend on, and
the failure it produces is the worst kind — silent and revenue-shaped.

The way it actually breaks: a buyer agent calls `POST /order`, gets back a
`payment_url`, and hands that link to its human. Its turn is over. The human
pays, minutes or hours later, in a browser the agent has no connection to.
Razorpay captures the money and the merchant's own dashboard reports the sale
as unpaid, indefinitely — because the only participant that knew to close the
loop had already finished and gone. Nothing in the manifest can fix that; a
buyer agent can read "confirm with POST /payment/verify" and still be a
process that no longer exists by the time payment happens.

So settlement gets two paths of its own, neither of them routed through the
buyer:

**Webhook** (`settle_from_webhook`) — Razorpay tells us directly, the moment
it captures. This is the real mechanism, and the only one that settles an
order promptly with nobody watching. It requires the service to be reachable
from the internet and `RAZORPAY_WEBHOOK_SECRET` to be set.

**Reconciliation on read** (`reconcile_pending`) — before the merchant's
analytics are totalled, any still-unpaid order is re-checked against
Razorpay's own record. Slower and lazier: it settles nothing until somebody
looks. But it needs no public URL and no dashboard configuration, so it covers
a deployment where the webhook isn't set up, a webhook that was added after
some orders had already been paid, and the deliveries Razorpay drops.

Both are safe to run repeatedly and both end at `ledger.mark_paid`, which
ignores an order that is already paid.

The rule both obey, and the one that matters most here: **an order is only
settled if its id is already in this shop's ledger.** A payment made on a
payment link does not belong to the order we created — Razorpay mints its own
internal order for the link and attaches the payment to that. Marking the id
that arrives in a webhook payload as paid without checking would book a sale
against an order this shop has never heard of, while the real one carried on
showing unpaid. `handlers.verify_payment` already navigates this; here it is
enforced by construction, by only ever writing to an id `ledger.get_order`
recognises.
"""

import json
import logging
import threading
import time
from typing import Any, Optional

import ledger
from config import (
    RAZORPAY_WEBHOOK_SECRET,
    RECONCILE_COOLDOWN_SECONDS,
    RECONCILE_MAX_AGE_SECONDS,
)
from handlers import PAID_STATUSES, razorpay_client, verify_payment

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Razorpay events that mean money was actually captured. Deliberately a
# closed set: a webhook can be configured in the dashboard to send far more
# than this (`payment.failed`, `payment_link.expired`, refunds), and an event
# this module does not understand must be acknowledged and ignored, never
# guessed at as a payment.
SETTLING_EVENTS = ("payment_link.paid", "order.paid", "payment.captured")


class WebhookRejected(Exception):
    """The delivery could not be trusted, so nothing was written.

    Separate from "understood but not actionable": a rejected delivery is a
    4xx and a real problem with the caller or the configuration, whereas an
    event about an order we don't own is a perfectly normal 200.
    """


def _entity(event: dict[str, Any], name: str) -> dict[str, Any]:
    """Pull `payload.<name>.entity` out of an event, tolerating its absence.

    Razorpay includes different entities depending on the event — a
    `payment_link.paid` carries both the link and the payment, an
    `order.paid` carries the order and the payment — and a missing one is
    normal rather than malformed.
    """
    entity = ((event.get("payload") or {}).get(name) or {}).get("entity")
    return entity if isinstance(entity, dict) else {}


def _candidate_order_ids(event: dict[str, Any]) -> list[str]:
    """Every id in this event that might be one of OUR order ids, best first.

    Ordered by how much we trust it to be ours:

    1. The payment link's `reference_id` — we set it to our order id in
       `handlers.create_payment_link` precisely so the link can be traced
       back here, so it is the most reliable field in the whole payload.
    2. The link's `notes.order_id` — same value, set at the same time, kept
       as a fallback for a link created before `reference_id` was populated.
    3. The order entity's own id, on an `order.paid`. For a browser checkout
       this IS our order. For a payment link it is Razorpay's internal one,
       which is why the ledger check downstream is not optional.
    4. The payment's `order_id` and notes, last, for the same reason.

    Every candidate is filtered through the ledger by the caller, so a wrong
    guess here settles nothing — it just falls through to the next one.
    """
    link = _entity(event, "payment_link")
    order = _entity(event, "order")
    payment = _entity(event, "payment")

    candidates = [
        link.get("reference_id"),
        (link.get("notes") or {}).get("order_id"),
        order.get("id"),
        payment.get("order_id"),
        (payment.get("notes") or {}).get("order_id"),
    ]

    seen: set[str] = set()
    unique: list[str] = []
    for candidate in candidates:
        if isinstance(candidate, str) and candidate and candidate not in seen:
            seen.add(candidate)
            unique.append(candidate)
    return unique


def _verify_signature(raw_body: bytes, signature: Optional[str]) -> None:
    """Prove the delivery came from Razorpay, or refuse it.

    This signature is the *only* authentication the webhook route has, which
    is why an unset secret fails closed instead of waving deliveries through:
    the endpoint writes revenue, and an unauthenticated writer of revenue is
    strictly worse than a shop that settles late.

    The HMAC is over the exact bytes Razorpay sent. Re-serialising the parsed
    JSON would change key order and whitespace and never match, so the raw
    body is what gets verified and the parse happens afterwards.
    """
    if not RAZORPAY_WEBHOOK_SECRET:
        raise WebhookRejected(
            "This deployment has no RAZORPAY_WEBHOOK_SECRET, so webhook deliveries "
            "cannot be authenticated and are refused."
        )
    if not signature:
        raise WebhookRejected("Missing X-Razorpay-Signature header.")

    try:
        razorpay_client.utility.verify_webhook_signature(
            raw_body.decode("utf-8"), signature, RAZORPAY_WEBHOOK_SECRET
        )
    except UnicodeDecodeError as e:
        raise WebhookRejected(f"Body is not valid UTF-8: {e}") from e
    except Exception as e:
        # razorpay raises SignatureVerificationError; catching broadly keeps a
        # change in the SDK's exception type from turning a forged delivery
        # into a 500 that some proxies would retry.
        raise WebhookRejected(f"Signature verification failed: {e}") from e


def settle_from_webhook(raw_body: bytes, signature: Optional[str]) -> dict[str, Any]:
    """Settle an order from a Razorpay webhook delivery.

    Args:
        raw_body: The exact request body bytes, needed for the HMAC.
        signature: The `X-Razorpay-Signature` header.

    Returns:
        Dict describing what was done, always with `handled` (whether the
        ledger changed) and `event`. Never raises for a delivery that is
        genuine but not actionable — an event about someone else's order, or a
        second delivery of one already settled, is a success as far as
        Razorpay needs to know, and a non-2xx would only earn a retry of
        something that will never become actionable.

    Raises:
        WebhookRejected: The delivery failed authentication or wasn't JSON.
            The route turns this into a 4xx.
    """
    _verify_signature(raw_body, signature)

    try:
        event = json.loads(raw_body)
    except json.JSONDecodeError as e:
        raise WebhookRejected(f"Body is not valid JSON: {e}") from e
    if not isinstance(event, dict):
        raise WebhookRejected("Body is not a JSON object.")

    name = event.get("event") or "unknown"
    if name not in SETTLING_EVENTS:
        logger.info(f"Webhook: ignoring {name}, not a settlement event")
        return {"handled": False, "event": name, "reason": "not_a_settlement_event"}

    payment = _entity(event, "payment")
    payment_status = payment.get("status")
    if payment_status and payment_status not in PAID_STATUSES:
        # A settlement-shaped event whose payment isn't actually captured.
        # Shouldn't happen, but the ledger is the wrong place to find out.
        logger.warning(f"Webhook: {name} carried payment status {payment_status}; ignoring")
        return {"handled": False, "event": name, "reason": "payment_not_captured"}

    # Which rail the shopper actually used. A link entity in the payload is
    # the distinguishing fact: `payment.captured` alone means Razorpay's
    # browser Checkout settled our order directly.
    paid_via = "payment_link" if _entity(event, "payment_link") else "checkout"

    for candidate in _candidate_order_ids(event):
        if not ledger.get_order(candidate):
            continue

        record = ledger.mark_paid(candidate, payment.get("id"), paid_via=paid_via)
        logger.info(f"Webhook: {name} settled {candidate} via {paid_via}")
        return {
            "handled": True,
            "event": name,
            "order_id": candidate,
            "payment_id": payment.get("id"),
            "paid_via": paid_via,
            "status": (record or {}).get("status"),
        }

    # Genuine delivery, just not about an order this shop recorded — another
    # integration on the same Razorpay account, or an order created before
    # the ledger existed.
    logger.info(f"Webhook: {name} matched no order in this ledger; acknowledged")
    return {"handled": False, "event": name, "reason": "no_matching_order"}


_reconcile_lock = threading.Lock()
_last_reconcile = 0.0


def reconcile_pending(force: bool = False) -> dict[str, Any]:
    """Re-check unsettled orders against Razorpay and settle the paid ones.

    The backstop for every case the webhook doesn't cover: no public URL, a
    webhook added after the fact, or a delivery that never arrived. Uses
    `handlers.verify_payment`, which already knows to look at the order's
    payment link and not just the order — the exact reason a link-paid order
    otherwise reads as `created` forever.

    Read-only against Razorpay (it never captures or refunds), so calling it
    on a dashboard read is safe. Two things keep it from being expensive:
    orders past the payment link's TTL are skipped, since an expired link can
    no longer be paid, and a cooldown collapses a burst of reads into one
    pass.

    Args:
        force: Ignore the cooldown. For an explicit "reconcile now", not for
            routine reads.

    Returns:
        Dict with `checked`, `settled` (the order ids that moved) and
        `skipped_cooldown`. Never raises: reconciliation is an enrichment
        step on someone else's request, and a Razorpay outage must degrade
        the number shown, not fail the dashboard.
    """
    global _last_reconcile

    with _reconcile_lock:
        now = time.time()
        if not force and now - _last_reconcile < RECONCILE_COOLDOWN_SECONDS:
            return {"checked": 0, "settled": [], "skipped_cooldown": True}
        _last_reconcile = now

        settled: list[str] = []
        checked = 0

        for record in ledger.pending_orders():
            order_id = record.get("order_id")
            created_at = record.get("created_at") or 0
            if not order_id:
                continue
            if now - created_at > RECONCILE_MAX_AGE_SECONDS:
                continue

            checked += 1
            try:
                result = verify_payment(order_id)
            except Exception as e:
                logger.warning(f"Reconcile: could not verify {order_id}: {e}")
                continue

            if result.get("status") not in PAID_STATUSES:
                continue

            # `verify_payment` resolves which id belongs to this ledger; the
            # fallback covers a result that omits it.
            resolved = result.get("order_id") or order_id
            if ledger.mark_paid(resolved, result.get("payment_id"), result.get("paid_via")):
                settled.append(resolved)

        if settled:
            logger.info(f"Reconcile: settled {len(settled)} order(s): {', '.join(settled)}")
        return {"checked": checked, "settled": settled, "skipped_cooldown": False}
