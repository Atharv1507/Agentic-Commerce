from typing import Any

TOOLS_SCHEMA: list[dict[str, Any]] = [
    {
        "type": "function",
        "function": {
            "name": "search_catalog",
            "description": "Search products by natural language query with optional filters.",
            "parameters": {
                "type": "object",
                "properties": {
                    "query": {
                        "type": "string",
                        "description": "Natural language search query (e.g., 'lightweight running shoes')",
                    },
                    "max_price": {
                        "type": "integer",
                        "description": "Maximum price filter in INR (optional)",
                    },
                    "gender": {
                        "type": "string",
                        "description": "Gender filter: 'Men', 'Women', or 'Unisex' (optional)",
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
