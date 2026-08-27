from typing import Any

TOOLS_SCHEMA: list[dict[str, Any]] = [
    {
        "type": "function",
        "function": {
            "name": "message_seller",
            "description": "Send a message to the seller agent to search products, check stock, or create orders.",
            "parameters": {
                "type": "object",
                "properties": {
                    "text": {
                        "type": "string",
                        "description": "The message to send to the seller (e.g., 'Show me black running shoes under 10000')",
                    }
                },
                "required": ["text"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "ask_user",
            "description": "Ask the user a clarifying question. Use when you need more information to formulate a query.",
            "parameters": {
                "type": "object",
                "properties": {
                    "question": {
                        "type": "string",
                        "description": "The question to ask the user",
                    },
                    "options": {
                        "type": "array",
                        "items": {"type": "string"},
                        "description": "Optional quick-reply options for the user",
                    },
                },
                "required": ["question"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "pay_order",
            "description": "Create a Razorpay order and process payment for selected products.",
            "parameters": {
                "type": "object",
                "properties": {
                    "product_ids": {
                        "type": "array",
                        "items": {"type": "string"},
                        "description": "List of product IDs to order",
                    },
                    "amount": {
                        "type": "integer",
                        "description": "Total amount in INR",
                    },
                    "buyer_name": {
                        "type": "string",
                        "description": "Name of the buyer",
                    },
                    "buyer_email": {
                        "type": "string",
                        "description": "Email of the buyer",
                    },
                    "buyer_phone": {
                        "type": "string",
                        "description": "Phone number of the buyer",
                    },
                    "buyer_address": {
                        "type": "string",
                        "description": "Delivery address",
                    },
                },
                "required": [
                    "product_ids",
                    "amount",
                    "buyer_name",
                    "buyer_email",
                    "buyer_phone",
                    "buyer_address",
                ],
            },
        },
    },
]
