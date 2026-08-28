"""Tool schemas for the seller's own model, and request models for its API.

Two different audiences, deliberately kept in one file so they can't drift:

- `TOOLS_SCHEMA` is what this service's LLM sees. Internal.
- The Pydantic models below are what a *foreign buyer agent* sees, because
  they are attached to real FastAPI routes and therefore show up in
  `/openapi.json` and in the discovery manifest via `model_json_schema()`.
  Before these existed, the only documented shape was `{session_id, text}` —
  a buyer had to reverse-engineer the useful parameters from this file's
  source. Now the machine-readable schema is generated from the same models
  the server validates against, so it cannot describe a contract the service
  doesn't honour.
"""

from typing import Any, Optional

from pydantic import BaseModel, Field


class BuyerContext(BaseModel):
    """What the buyer's agent reports about the shopper it represents.

    Self-reported and unverified — there is no cross-merchant identity to
    check it against. It may therefore only ever unlock a discount (lifecycle
    campaigns), never raise a price or grant an entitlement, so a buyer agent
    lying here can only cost the merchant margin, never harm the shopper.
    """

    order_count: Optional[int] = Field(
        default=None, description="How many orders this shopper has placed with this merchant."
    )
    days_since_last_order: Optional[float] = Field(
        default=None, description="Days since their previous order, for win-back offers."
    )
    lifetime_spend_inr: Optional[int] = Field(
        default=None, description="Total historical spend in rupees."
    )


class SearchBrief(BaseModel):
    """A structured product brief, mirroring what `search_catalog` accepts.

    Every field is optional so a buyer can state only the constraints it
    actually has. This is rendered into a canonical instruction server-side
    and then handed to the seller's own reasoning loop — it is not a filter
    that bypasses the merchant's judgement.
    """

    query: Optional[str] = Field(
        default=None,
        description=(
            "Product type and style only, e.g. 'linen casual shirt'. Do not put price, "
            "colour, brand or gender here — each has its own field, and only the field "
            "actually constrains the search."
        ),
    )
    max_price: Optional[int] = Field(default=None, description="Ceiling in rupees.")
    min_price: Optional[int] = Field(default=None, description="Floor in rupees.")
    target_price: Optional[int] = Field(
        default=None, description="The price point to aim at, in rupees."
    )
    gender: Optional[str] = Field(default=None, description="Men, Women or Unisex.")
    colors: Optional[list[str]] = Field(default=None, description="Acceptable colours.")
    materials: Optional[list[str]] = Field(
        default=None, description="Acceptable fabrics, e.g. cotton, linen."
    )
    brands: Optional[list[str]] = Field(default=None, description="Acceptable brands.")
    size: Optional[str] = Field(
        default=None, description="XS-XXL. A hard filter: results can actually be worn."
    )
    exclude_ids: Optional[list[str]] = Field(
        default=None, description="Product IDs already shown, so they are not re-offered."
    )
    top_k: Optional[int] = Field(default=None, description="How many results to return.")


class MessageRequest(BaseModel):
    """One brief from a buyer agent — structured, free-text, or both."""

    session_id: str = Field(
        description=(
            "Scopes the seller's memory to ONE negotiation. Namespaced per "
            "authenticated buyer server-side, so your ids cannot collide with "
            "another buyer's."
        )
    )
    text: Optional[str] = Field(
        default=None,
        description="A natural-language brief. Optional when `brief` is supplied.",
    )
    brief: Optional[SearchBrief] = Field(
        default=None,
        description=(
            "A structured brief. Rendered into a canonical instruction and passed "
            "through the merchant's own reasoning, exactly as free text is."
        ),
    )
    buyer_context: Optional[BuyerContext] = None


class OrderRequest(BaseModel):
    """Everything needed to create and pay for an order."""

    product_ids: list[str] = Field(
        description="Product IDs to order. Repeat an ID once per unit wanted."
    )
    buyer_name: str
    buyer_address: str
    buyer_email: str
    buyer_phone: str
    sizes: Optional[dict[str, str]] = Field(
        default=None, description="Size per product ID, when they differ per item."
    )
    buyer_size: Optional[str] = Field(
        default=None, description="Fallback size for any product not listed in `sizes`."
    )
    purposes: Optional[dict[str, str]] = Field(
        default=None,
        description=(
            "'primary' or 'complement' per product ID. Mark a line 'complement' only "
            "when it was an accepted cross-sell. Used for the merchant's attach-rate "
            "reporting; it does not affect price."
        ),
    )
    buyer_context: Optional[BuyerContext] = None


class VerifyPaymentRequest(BaseModel):
    """Ask the merchant to confirm a payment against Razorpay."""

    order_id: str
    payment_id: Optional[str] = Field(
        default=None,
        description="Preferred when known — the payment is the authoritative record.",
    )


class FacetsRequest(BaseModel):
    """Which choices actually exist for a product type."""

    query: str
    gender: Optional[str] = None
    full: bool = Field(
        default=False,
        description="Complete facet lists rather than a form-sized subset.",
    )


class StockRequest(BaseModel):
    """Exact per-size availability for a set of products."""

    product_ids: list[str]
    size: Optional[str] = None


TOOLS_SCHEMA: list[dict[str, Any]] = [
    {
        "type": "function",
        "function": {
            "name": "search_catalog",
            "description": (
                "Search products by natural language query with constraint filters. "
                "Pass EVERY constraint the buyer stated — price band, colours, brands, "
                "gender — as its own argument rather than burying it in the query "
                "string, otherwise it only weakly influences ranking."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "query": {
                        "type": "string",
                        "description": "The product type and style, e.g. 'analogue wrist watch' or 'floral summer dress'. Do NOT put prices, colours or brands here — use the dedicated arguments.",
                    },
                    "max_price": {
                        "type": "integer",
                        "description": "Hard maximum price in INR. Nothing above this is returned.",
                    },
                    "min_price": {
                        "type": "integer",
                        "description": "Hard minimum price in INR. Use it for 'premium'/'high-end' asks so budget items don't fill the results.",
                    },
                    "target_price": {
                        "type": "integer",
                        "description": "The price to rank towards, normally the buyer's stated budget or a little under it. A buyer who says '10k' wants options near 10k, not near zero — always set this when a budget is mentioned.",
                    },
                    "gender": {
                        "type": "string",
                        "description": "Gender filter: 'Men', 'Women', or 'Unisex'. Unisex products always pass.",
                    },
                    "colors": {
                        "type": "array",
                        "items": {"type": "string"},
                        "description": "Preferred colours, e.g. ['grey']. Matched by colour family, so 'grey' also accepts charcoal and slate.",
                    },
                    "materials": {
                        "type": "array",
                        "items": {"type": "string"},
                        "description": "Preferred fabrics, e.g. ['linen']. Ranking preference, not a hard filter — each returned product carries matches_material so you can say when none actually are.",
                    },
                    "brands": {
                        "type": "array",
                        "items": {"type": "string"},
                        "description": "Preferred brands, e.g. ['CASIO']. Use this for 'something like <brand>' asks.",
                    },
                    "size": {
                        "type": "string",
                        "description": "The buyer's size: XS, S, M, L, XL or XXL. A HARD filter — only products with stock in that size come back. Always pass it when the brief states one; a garment the buyer cannot wear is not a result.",
                    },
                    "exclude_ids": {
                        "type": "array",
                        "items": {"type": "string"},
                        "description": "Product IDs already shown to this buyer. Always pass these when asked for different/more options.",
                    },
                    "top_k": {
                        "type": "integer",
                        "description": "How many results to return (default 5).",
                    },
                },
                "required": ["query"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "price_range",
            "description": (
                "Report what a product type actually costs in this catalogue "
                "(min/median/max). Call this when a search comes back short or "
                "far off the buyer's budget, so you can tell them the real range "
                "instead of silently returning items at the wrong price."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "query": {
                        "type": "string",
                        "description": "The product type, e.g. 'analogue wrist watch'",
                    },
                    "gender": {
                        "type": "string",
                        "description": "Optional gender filter",
                    },
                },
                "required": ["query"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "check_stock",
            "description": (
                "Check per-size availability for one product. Use before creating an "
                "order, and whenever the buyer asks about a specific size. Returns the "
                "unit count for every size, so answer from those numbers rather than "
                "assuming a product exists in the size that was asked about."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "product_id": {
                        "type": "string",
                        "description": "The product ID to check",
                    },
                    "size": {
                        "type": "string",
                        "description": "The size being asked about (XS, S, M, L, XL, XXL). Pass it whenever the buyer named one — the answer then refers to that size specifically instead of the product in general.",
                    },
                },
                "required": ["product_id"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "create_order",
            "description": (
                "Create a Razorpay order for one or more products. Re-validates size "
                "stock at order time and refuses the order if any line cannot ship in "
                "the requested size."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "product_ids": {
                        "type": "array",
                        "items": {"type": "string"},
                        "description": "List of product IDs to order",
                    },
                    "buyer_name": {
                        "type": "string",
                        "description": "Name of the buyer",
                    },
                    "buyer_address": {
                        "type": "string",
                        "description": "Delivery address",
                    },
                    "buyer_email": {
                        "type": "string",
                        "description": "Email of the buyer",
                    },
                    "buyer_phone": {
                        "type": "string",
                        "description": "Phone number of the buyer",
                    },
                    "sizes": {
                        "type": "object",
                        "description": "Size per product, keyed by product ID, e.g. {\"prod_0007\": \"L\"}. Use when the buyer named different sizes for different items.",
                        "additionalProperties": {"type": "string"},
                    },
                    "buyer_size": {
                        "type": "string",
                        "description": "The buyer's usual size, applied to any product not listed in `sizes`.",
                    },
                    "purposes": {
                        "type": "object",
                        "description": (
                            "Optional \"primary\" or \"complement\" per product, keyed by "
                            "product ID. Mark a line \"complement\" only when it was a "
                            "cross-sell the buyer accepted rather than something they "
                            "originally asked for. Anything unlisted counts as primary."
                        ),
                        "additionalProperties": {"type": "string"},
                    },
                },
                "required": ["product_ids", "buyer_name", "buyer_address", "buyer_email", "buyer_phone"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "evaluate_offers",
            "description": (
                "Check which of the shop's live campaigns apply to a prospective "
                "basket — threshold discounts, the shirt + T-shirt bundle, cross-sell "
                "pairings and lifecycle offers. Read-only: it changes no price. Call it "
                "once you know roughly what the buyer is assembling, then decide "
                "whether an offer is worth raising. Never quote a discount this tool "
                "did not return."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "product_ids": {
                        "type": "array",
                        "items": {"type": "string"},
                        "description": (
                            "The products under discussion. Repeat an ID once per unit. "
                            "Preferred over cart_total_inr — real products carry the "
                            "category information the bundle rule needs."
                        ),
                    },
                    "cart_total_inr": {
                        "type": "integer",
                        "description": (
                            "A basket value in rupees, for when the buyer stated a total "
                            "without naming products. Ignored if product_ids is given."
                        ),
                    },
                },
                "required": [],
            },
        },
    },
]
