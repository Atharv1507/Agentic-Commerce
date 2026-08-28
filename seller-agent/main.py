import json
import logging
import os
from concurrent.futures import ThreadPoolExecutor
from typing import Any, Optional

from fastapi import Depends, FastAPI
from fastapi.middleware.cors import CORSMiddleware
from openai import OpenAI
from dotenv import load_dotenv

from analytics import merchant_analytics
from auth import require_buyer, require_merchant, scoped_session_id
from config import (
    BUYER_KEY_HEADER,
    DASHBOARD_ORIGINS,
    MERCHANT_CATEGORIES,
    MERCHANT_CURRENCY,
    MERCHANT_DESCRIPTION,
    MERCHANT_KEY_HEADER,
    MERCHANT_NAME,
    MERCHANT_PRICE_RANGE_INR,
    SYSTEM_PROMPT,
    USING_DEMO_KEYS,
    OPENAI_MODEL,
    SELLER_AGENT_PORT,
    SESSION_HISTORY_LIMIT,
    MAX_TOOL_ITERATIONS,
)
from schemas import (
    FacetsRequest,
    MessageRequest,
    OrderRequest,
    SearchBrief,
    StockRequest,
    TOOLS_SCHEMA,
    VerifyPaymentRequest,
)
from handlers import check_stock, create_order, execute_tool, verify_payment
import ledger
from rag import catalog_facets

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

load_dotenv()

app = FastAPI(title="Seller Agent")

# Agent-to-agent traffic is server-to-server and needs no CORS at all. This
# exists for exactly one caller: the merchant analytics dashboard in the React
# app, which is a browser. Scoped to the dashboard's own origins rather than
# "*" so opening the manifest in a tab doesn't hand any page on the internet a
# credentialed path to this service.
app.add_middleware(
    CORSMiddleware,
    allow_origins=DASHBOARD_ORIGINS,
    allow_credentials=False,
    allow_methods=["GET", "POST", "DELETE"],
    allow_headers=[BUYER_KEY_HEADER, MERCHANT_KEY_HEADER, "Content-Type"],
)

openai_client = OpenAI(api_key=os.getenv("OPENAI_API_KEY"))

# One entry per NEGOTIATION, not per buyer. The Personal Agent opens a fresh
# session id for each search and deletes it when the search ends, so the seller
# has context across the rounds of one negotiation and none at all between
# separate searches. Sharing a session per buyer meant a failed search stayed in
# the seller's head: asked about trousers, it would still answer about the linen
# shirts it couldn't find earlier.
sessions: dict[str, list[dict[str, Any]]] = {}
_session_order: list[str] = []
# Backstop in case a caller never deletes its session (crash, timeout).
MAX_SESSIONS = 200

# Buyer agents read `tool_results` and ignore the natural-language reply — the
# bundled Personal Agent does exactly this (see negotiation.py's
# `_products_from_reply`), and the manifest documents `tool_results` as the
# contract, so any buyer is expected to. Once a round's tool calls are all
# read-only lookups, there is nothing left for another completion to decide, so
# paying for an extra model call to write a summary nobody reads is pure
# latency. `create_order` is deliberately excluded — a real mutation still gets
# the model's full multi-round reasoning.
#
# `evaluate_offers` belongs here for the same reason: it is genuinely read-only,
# and the prose would be discarded anyway. The seller's LLM still owns the
# decision that matters — *whether* an offer is relevant enough to look up and
# return at all. The wording a shopper sees is composed by the buyer's own agent
# from the structured offer, exactly as it already is for products.
READ_ONLY_TOOLS = {"search_catalog", "price_range", "check_stock", "evaluate_offers"}

# Tool execution is I/O-bound (Chroma query, catalogue lookups) and independent
# across calls in the same round, so run them concurrently instead of one at a
# time. Small pool: a round realistically has a couple of tool calls, not many.
_tool_executor = ThreadPoolExecutor(max_workers=4)


def _touch_session(session_id: str) -> list[dict[str, Any]]:
    """Get or open a session, evicting the oldest once we're over the cap."""
    if session_id not in sessions:
        sessions[session_id] = []
        _session_order.append(session_id)
        while len(_session_order) > MAX_SESSIONS:
            evicted = _session_order.pop(0)
            sessions.pop(evicted, None)
    return sessions[session_id]


def _drop_session(session_id: str) -> bool:
    existed = sessions.pop(session_id, None) is not None
    if session_id in _session_order:
        _session_order.remove(session_id)
    return existed


def build_messages(history: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Assemble the message list for one model call.

    A `tool` message is only valid when the assistant message that requested it
    is present too. Taking a fixed-size tail can strand tool replies at the
    front of the window, which the API rejects — so skip any that the cut
    exposed.
    """
    window = history[-SESSION_HISTORY_LIMIT:]
    start = 0
    while start < len(window) and window[start].get("role") == "tool":
        start += 1
    return [{"role": "system", "content": SYSTEM_PROMPT}] + window[start:]


def render_brief(brief: SearchBrief) -> str:
    """Turn a structured brief into the canonical instruction this shop reads.

    This is the merchant's own template, not the buyer's. It exists so a
    foreign buyer agent can express constraints in a documented schema instead
    of reverse-engineering the exact English that happens to steer this
    service's model — which is what the bundled Personal Agent had to do.

    Note what this deliberately does NOT do: it does not filter, rank, or
    shortcut anything. The rendered text goes through the same tool-calling
    loop as free-form prose, so the merchant's reasoning applies identically
    either way. A structured caller gets a stable contract, not a fast path
    around the seller's judgement.
    """
    parts: list[str] = []
    if brief.query:
        parts.append(f"Find: {brief.query}.")
    else:
        parts.append("Find products matching the constraints below.")

    if brief.gender:
        parts.append(f"Gender: {brief.gender}.")
    if brief.size:
        parts.append(f"Pass size={brief.size} to search_catalog as a hard filter.")

    band: list[str] = []
    if brief.target_price is not None:
        band.append(f"target_price={brief.target_price}")
    if brief.min_price is not None:
        band.append(f"min_price={brief.min_price}")
    if brief.max_price is not None:
        band.append(f"max_price={brief.max_price}")
    if band:
        parts.append(f"Set {', '.join(band)} (rupees).")

    if brief.colors:
        parts.append(f"Pass colors={brief.colors}.")
    if brief.materials:
        parts.append(f"Pass materials={brief.materials}.")
    if brief.brands:
        parts.append(f"Pass brands={brief.brands}.")
    if brief.exclude_ids:
        parts.append(f"Pass exclude_ids={brief.exclude_ids} — do not re-offer these.")
    if brief.top_k:
        parts.append(f"Return up to {brief.top_k} results.")

    return " ".join(parts)


def _run_conversation(
    session_id: str, text: str, buyer_context: Optional[dict[str, Any]] = None
) -> dict[str, Any]:
    """Run one brief through the tool-calling loop and return the reply.

    Args:
        session_id: Already buyer-scoped (see `auth.scoped_session_id`).
        text: The brief, whether typed by a buyer agent or rendered from a
            structured one — by this point they are indistinguishable, which
            is the point.
        buyer_context: Passed through to tools out-of-band, never exposed as a
            tool argument the model could fabricate.

    Returns:
        Dict with `response` and `tool_results`.
    """
    history = _touch_session(session_id)
    history.append({"role": "user", "content": text})

    try:
        all_tool_results: list[dict[str, Any]] = []
        final_message: Optional[str] = None

        for _ in range(MAX_TOOL_ITERATIONS):
            response = openai_client.chat.completions.create(
                model=OPENAI_MODEL,
                messages=build_messages(history),
                tools=TOOLS_SCHEMA,
                tool_choice="auto",
            )
            assistant_message = response.choices[0].message

            if not assistant_message.tool_calls:
                final_message = assistant_message.content
                break

            logger.info(
                f"Tool calls: {[tc.function.name for tc in assistant_message.tool_calls]}"
            )

            history.append(
                {
                    "role": "assistant",
                    "content": assistant_message.content or "",
                    "tool_calls": [
                        {
                            "id": tc.id,
                            "type": "function",
                            "function": {
                                "name": tc.function.name,
                                "arguments": tc.function.arguments,
                            },
                        }
                        for tc in assistant_message.tool_calls
                    ],
                }
            )

            calls = assistant_message.tool_calls
            tool_names = {tc.function.name for tc in calls}
            # ThreadPoolExecutor.map preserves call order in its results, so
            # the concurrency is invisible to the history/audit bookkeeping
            # below — it still appends in the same order a sequential loop
            # would have.
            arg_list = [json.loads(tc.function.arguments or "{}") for tc in calls]
            results = list(
                _tool_executor.map(
                    lambda pair: execute_tool(
                        pair[0].function.name, pair[1], buyer_context=buyer_context
                    ),
                    zip(calls, arg_list),
                )
            )

            for tool_call, result in zip(calls, results):
                all_tool_results.append(
                    {
                        "tool_call_id": tool_call.id,
                        "tool": tool_call.function.name,
                        "result": result,
                    }
                )
                history.append(
                    {
                        "role": "tool",
                        "tool_call_id": tool_call.id,
                        "content": json.dumps(result),
                    }
                )

            if tool_names <= READ_ONLY_TOOLS:
                final_message = f"[{len(calls)} lookup(s) executed: {', '.join(sorted(tool_names))}]"
                break

        if final_message is None:
            logger.warning("Tool iteration budget exhausted; forcing a text response")
            response = openai_client.chat.completions.create(
                model=OPENAI_MODEL,
                messages=build_messages(history),
                tools=TOOLS_SCHEMA,
                tool_choice="none",
            )
            final_message = response.choices[0].message.content

        history.append({"role": "assistant", "content": final_message})

        return {"response": final_message, "tool_results": all_tool_results}

    except Exception as e:
        logger.error(f"Error: {e}")
        return {
            "response": "I'm having trouble processing your request. Please try again.",
            "tool_results": [],
        }


@app.post("/message")
async def handle_message(
    request: MessageRequest, buyer_id: str = Depends(require_buyer)
) -> dict[str, Any]:
    """Answer one brief from an authenticated buyer agent.

    Accepts a structured `brief`, free-form `text`, or both. A structured brief
    is rendered into this shop's canonical instruction and then runs through
    exactly the same reasoning loop as prose — the schema is a stable contract
    for the caller, not a way around the merchant's judgement.

    Args:
        request: session_id plus a brief, text, or both.
        buyer_id: Resolved from the API key; scopes the session namespace.

    Returns:
        Dict with response and tool_results.
    """
    if not request.text and not request.brief:
        return {
            "response": "Send either `text` or `brief`. See /.well-known/agent.json.",
            "tool_results": [],
            "error": True,
        }

    segments = []
    if request.brief:
        segments.append(render_brief(request.brief))
    if request.text:
        segments.append(request.text)
    # Brief first, then any free text: the text is where a buyer adds nuance
    # the schema can't carry ("nothing too formal"), and it reads as a
    # qualification of the brief rather than a competing instruction.
    brief_text = "\n".join(segments)

    return _run_conversation(
        scoped_session_id(buyer_id, request.session_id),
        brief_text,
        buyer_context=request.buyer_context.model_dump() if request.buyer_context else None,
    )


@app.delete("/session/{session_id}")
async def delete_session(
    session_id: str, buyer_id: str = Depends(require_buyer)
) -> dict[str, Any]:
    """Forget a negotiation's history once the buyer's agent is done with it.

    Scoped to the calling buyer, so this can only ever drop the caller's own
    session — previously any caller could delete any session id it could guess.

    Args:
        session_id: The negotiation session to drop.
        buyer_id: Resolved from the API key.

    Returns:
        Dict with status.
    """
    existed = _drop_session(scoped_session_id(buyer_id, session_id))
    return {"status": "ok", "deleted": existed}


@app.post("/order")
async def create_order_route(
    request: OrderRequest, buyer_id: str = Depends(require_buyer)
) -> dict[str, Any]:
    """Create a Razorpay order for a buyer agent, and record it in the ledger.

    Deliberately not an LLM call. Stock is re-validated, pricing comes from the
    campaign engine, and both are exact — the same reasoning that keeps
    `/facets` and `/stock` model-free applies with more force to the one route
    that takes money.

    The merchant creates the order because the merchant owns the Razorpay
    account. A buyer agent holding merchant payment credentials would not be a
    buyer agent; it would be the shop.

    Args:
        request: Products, buyer details, sizes, cross-sell markers.
        buyer_id: Resolved from the API key. Recorded on the order as the
            revenue attribution for the merchant's analytics.

    Returns:
        The order, or an error explaining why it could not be created.
    """
    result = create_order(
        request.product_ids,
        request.buyer_name,
        request.buyer_address,
        request.buyer_email,
        request.buyer_phone,
        sizes=request.sizes,
        buyer_size=request.buyer_size,
        purposes=request.purposes,
        buyer_context=request.buyer_context.model_dump() if request.buyer_context else None,
    )

    if result.get("order_id"):
        ledger.record_order(
            order_id=result["order_id"],
            buyer_id=buyer_id,
            subtotal_inr=result["subtotal_inr"],
            discount_inr=result["discount_inr"],
            amount_inr=result["amount_inr"],
            currency=result["currency"],
            lines=result["lines"],
            applied_campaign=result.get("applied_campaign"),
        )
    return result


@app.post("/payment/verify")
async def verify_payment_route(
    request: VerifyPaymentRequest, buyer_id: str = Depends(require_buyer)
) -> dict[str, Any]:
    """Confirm a payment with Razorpay and settle the order in the ledger.

    Read-only against Razorpay — it never captures or refunds — so it is safe
    to call more than once.

    Args:
        request: The order id, and the payment id when known.
        buyer_id: Resolved from the API key.

    Returns:
        The payment status.
    """
    result = verify_payment(request.order_id, request.payment_id)

    if result.get("status") in ("captured", "paid"):
        # Keyed off Razorpay's own answer rather than the caller's claim: a
        # buyer agent saying "this is paid" is not evidence that it is.
        ledger.mark_paid(result.get("order_id") or request.order_id, result.get("payment_id"))
    return result


@app.get("/merchant/analytics")
async def merchant_analytics_route(
    _: str = Depends(require_merchant),
) -> dict[str, Any]:
    """The merchant's own numbers, aggregated from the order ledger.

    Behind the merchant credential, not a buyer key — revenue split by buyer
    agent is precisely the thing one buyer agent must not be able to read
    about another.
    """
    return {"status": "ok", **merchant_analytics()}


@app.get("/.well-known/agent.json")
async def agent_card() -> dict[str, Any]:
    """Self-describing manifest: what this merchant sells and how to buy it.

    Served at the RFC 8615 well-known path and left unauthenticated on
    purpose — a buyer agent has to be able to read how to obtain a key before
    it has one, and nothing here is a secret.

    `capabilities` comes first and is written for an agent deciding *whether*
    to engage; `interface` carries the callable detail for one that already
    has. The request schemas are generated from the same Pydantic models the
    routes validate against, so this manifest cannot describe a contract the
    service does not actually honour.

    Note on discovery: this answers "how do I transact with this merchant",
    given its base URL. It does not answer "which merchants exist" — that is a
    registry problem (the ground the ACP/AP2 efforts are contesting), and
    deliberately out of scope here.
    """
    return {
        "protocol_version": "0.1",
        "merchant": {
            "name": MERCHANT_NAME,
            "description": MERCHANT_DESCRIPTION,
            "categories": MERCHANT_CATEGORIES,
            "price_range_inr": MERCHANT_PRICE_RANGE_INR,
            "currency": MERCHANT_CURRENCY,
        },
        "capabilities": [
            {
                "name": "catalog_search",
                "summary": (
                    "Describe what you want and this merchant's own agent searches its "
                    "catalogue and returns curated matches. The raw catalogue is never "
                    "exposed; the merchant decides what is relevant."
                ),
            },
            {
                "name": "negotiate",
                "summary": (
                    "Push back on results — too expensive, wrong colour, show me others — "
                    "and the merchant will re-search against the corrected brief. Multiple "
                    "rounds within one session share context."
                ),
            },
            {
                "name": "clarify",
                "summary": (
                    "Ask which colours, brands, fabrics and price bands actually exist "
                    "for a product type before committing to a brief."
                ),
            },
            {
                "name": "stock_check",
                "summary": "Exact per-size unit counts, so you never sell a size that cannot ship.",
            },
            {
                "name": "bundle_offers",
                "summary": (
                    "The merchant runs live campaigns — threshold discounts and a "
                    "shirt + T-shirt bundle. Ask what applies to a basket; the best "
                    "single one is applied automatically at order time."
                ),
            },
            {
                "name": "cross_sell",
                "summary": (
                    "The merchant will suggest a genuinely complementary item when one "
                    "exists, and says nothing when one does not."
                ),
            },
            {
                "name": "lifecycle_offers",
                "summary": (
                    "First-order and win-back discounts, unlocked by optional shopper "
                    "history you supply. Unverified, so it can only ever reduce a price."
                ),
            },
            {
                "name": "purchase",
                "summary": (
                    "The merchant creates the Razorpay order. You never need — and never "
                    "receive — the merchant's payment credentials."
                ),
            },
            {
                "name": "payment_verification",
                "summary": "Confirm a completed payment against Razorpay's own record.",
            },
        ],
        "auth": {
            "type": "api_key_header",
            "header": BUYER_KEY_HEADER,
            "how_to_obtain": (
                "Contact the merchant for a buyer key. This demo build ships with a "
                "static test key; a production merchant would issue one per buyer agent."
            ),
            "note": (
                "Your key identifies your agent. Session ids you send are namespaced "
                "under it, so they cannot collide with another buyer's."
            ),
        },
        "interface": {
            "search_and_negotiate": {
                "endpoint": "POST /message",
                "description": (
                    "Send `brief` (structured), `text` (natural language), or both. "
                    "Both run through the merchant's reasoning identically."
                ),
                "request_schema": MessageRequest.model_json_schema(),
            },
            "clarify": {
                "endpoint": "POST /facets",
                "description": "Non-LLM: exact facets that exist for a product type.",
                "request_schema": FacetsRequest.model_json_schema(),
            },
            "stock_check": {
                "endpoint": "POST /stock",
                "description": "Non-LLM: exact per-size stock for a list of product ids.",
                "request_schema": StockRequest.model_json_schema(),
            },
            "purchase": {
                "endpoint": "POST /order",
                "description": (
                    "Creates the Razorpay order. Re-validates stock and applies any "
                    "qualifying campaign. Read `amount_inr` for rupees; `amount` is paise."
                ),
                "request_schema": OrderRequest.model_json_schema(),
            },
            "payment_verification": {
                "endpoint": "POST /payment/verify",
                "request_schema": VerifyPaymentRequest.model_json_schema(),
            },
            "end_session": {
                "endpoint": "DELETE /session/{session_id}",
                "description": "Drop one negotiation's context when you're done with it.",
            },
        },
    }


@app.post("/facets")
async def facets(
    request: FacetsRequest, buyer_id: str = Depends(require_buyer)
) -> dict[str, Any]:
    """Report the choices that actually exist for a product type.

    Deliberately not an LLM call — the Personal Agent uses this to populate a
    clarifying question before searching, and that needs to be fast and to
    reflect real stock.

    Args:
        request: FacetsRequest with the product type and optional gender.

    Returns:
        Dict of available colours, brands, fabrics and price bands. With
        `full`, the complete lists — that mode answers a shopper's direct
        "what do you stock?" question rather than populating a form.
    """
    return catalog_facets(request.query, gender=request.gender, full=request.full)


@app.post("/stock")
async def stock(
    request: StockRequest, buyer_id: str = Depends(require_buyer)
) -> dict[str, Any]:
    """Per-size availability for a set of products, without an LLM in the way.

    The buyer's agent calls this at checkout to confirm every line can still
    ship in the shopper's size. That check has to be exact and fast, and an
    LLM round trip is neither — a model that paraphrases "0 in L" as "in
    stock" would let the shop take money for a garment it cannot send.

    Args:
        request: StockRequest with the product IDs and the size to check.

    Returns:
        Dict keyed by product ID, plus `unavailable` listing the IDs that
        cannot ship in that size.
    """
    results = {pid: check_stock(pid, request.size) for pid in request.product_ids}
    return {
        "size": request.size,
        "products": results,
        "unavailable": [
            pid for pid, r in results.items() if r.get("error") or not r.get("in_stock")
        ],
    }


@app.get("/health")
async def health() -> dict[str, Any]:
    """Health check endpoint.

    Reports `using_demo_keys` so "why is every call 401ing" and "why is this
    accepting anyone" are both answerable without reading the process log.
    """
    return {
        "status": "ok",
        "active_sessions": len(sessions),
        "using_demo_keys": USING_DEMO_KEYS,
    }


if __name__ == "__main__":
    import uvicorn

    uvicorn.run(app, host="0.0.0.0", port=SELLER_AGENT_PORT)
