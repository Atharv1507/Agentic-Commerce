from typing import Any

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
            "description": "Check if a product is in stock. Use before creating an order.",
            "parameters": {
                "type": "object",
                "properties": {
                    "product_id": {
                        "type": "string",
                        "description": "The product ID to check",
                    }
                },
                "required": ["product_id"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "create_order",
            "description": "Create a Razorpay order for one or more products.",
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
                },
                "required": ["product_ids", "buyer_name", "buyer_address", "buyer_email", "buyer_phone"],
            },
        },
    },
]
