"""Who is allowed to talk to this merchant, and as whom.

Every route on this service used to be reachable by anyone who could open a
socket to it, with `session_id` a caller-supplied string that nothing checked.
That was survivable only because exactly one process (the bundled Personal
Agent) ever called it. The moment a merchant is meant to be transactable by
*any* AI buyer, two things have to become true:

1. A caller has to prove which buyer agent it is, so an order can be
   attributed and so an unknown agent can be refused.
2. That identity has to scope the caller's session namespace, or two buyers
   picking the same `session_id` string would read and delete each other's
   negotiations (see `scoped_session_id`).

There are two separate credentials on purpose. A buyer key buys things; a
merchant key reads the shop's books. Handing a buyer the merchant key would
let one buyer agent see every other buyer agent's revenue contribution.
"""

import logging

from fastapi import Header, HTTPException

from config import (
    BUYER_API_KEYS,
    BUYER_KEY_HEADER,
    MERCHANT_API_KEY,
    MERCHANT_KEY_HEADER,
)

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


async def require_buyer(x_buyer_key: str = Header(None, alias=BUYER_KEY_HEADER)) -> str:
    """Resolve the calling buyer agent's id, or refuse the request.

    Returns the buyer_id rather than a bool because callers need it: it scopes
    their session namespace and it lands on every order in the ledger as the
    revenue attribution.

    Raises:
        HTTPException: 401 when the header is absent or the key is unknown.
            Deliberately the same status and detail for both, so a caller
            can't use the response to tell "no key" from "wrong key" and
            probe for valid ones.
    """
    buyer_id = BUYER_API_KEYS.get(x_buyer_key or "")
    if not buyer_id:
        # Logged without the attempted key — a rejected credential is still a
        # credential and does not belong in a log file.
        logger.warning("Rejected a buyer request: missing or unknown key")
        raise HTTPException(
            status_code=401,
            detail=(
                f"A valid {BUYER_KEY_HEADER} header is required. See "
                f"/.well-known/agent.json for how to obtain one."
            ),
        )
    return buyer_id


async def require_merchant(
    x_merchant_key: str = Header(None, alias=MERCHANT_KEY_HEADER),
) -> str:
    """Gate the merchant's own analytics behind the merchant credential.

    Raises:
        HTTPException: 401 when the header is absent or wrong, and also when
            no MERCHANT_API_KEY is configured at all — an unset key must not
            silently mean "everyone is the merchant".
    """
    if not MERCHANT_API_KEY or x_merchant_key != MERCHANT_API_KEY:
        logger.warning("Rejected a merchant analytics request")
        raise HTTPException(
            status_code=401,
            detail=f"A valid {MERCHANT_KEY_HEADER} header is required.",
        )
    return "merchant"


def scoped_session_id(buyer_id: str, session_id: str) -> str:
    """Namespace a caller-supplied session id under the authenticated buyer.

    The id a buyer sends is theirs to choose and is not unique across buyers —
    two agents both opening `"1"` is entirely likely. Prefixing with the
    authenticated buyer_id makes collision impossible, which also means
    `DELETE /session/{id}` can only ever reach the caller's own session.
    """
    return f"{buyer_id}::{session_id}"
