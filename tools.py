import os
import razorpay
from dotenv import load_dotenv
from rag import search_catalog, get_product_by_id

load_dotenv()

razorpay_client = razorpay.Client(auth=(
    os.getenv("RAZORPAY_KEY_ID"),
    os.getenv("RAZORPAY_KEY_SECRET")
))

def check_stock(product_id: str) -> dict:
    """Check stock availability for a product."""
    product = get_product_by_id(product_id)
    if not product:
        return {"error": "product_not_found"}
    
    return {
        "product_id": product_id,
        "in_stock": True,
        "stock_count": 10
    }

def create_order(product_id: str, buyer_name: str, buyer_address: str) -> dict:
    """Create a Razorpay order for the product."""
    product = get_product_by_id(product_id)
    if not product:
        return {"error": "product_not_found"}
    
    stock = check_stock(product_id)
    if stock.get("error") or not stock.get("in_stock"):
        return {"error": "out_of_stock"}
    
    try:
        order = razorpay_client.order.create({
            "amount": product["price"] * 100,
            "currency": "INR",
            "receipt": f"receipt_{product_id}"
        })
        
        return {
            "order_id": order["id"],
            "amount": order["amount"],
            "currency": order["currency"],
            "product": product
        }
    except Exception as e:
        print(f"Razorpay error: {e}")
        return {"error": "order_creation_failed"}

TOOLS_SCHEMA = [
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
                        "description": "Natural language search query (e.g., 'lightweight running shoes')"
                    },
                    "max_price": {
                        "type": "integer",
                        "description": "Maximum price filter in INR (optional)"
                    },
                    "gender": {
                        "type": "string",
                        "description": "Gender filter: 'Men', 'Women', or 'Unisex' (optional)"
                    }
                },
                "required": ["query"]
            }
        }
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
                        "description": "The product ID to check"
                    }
                },
                "required": ["product_id"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "create_order",
            "description": "Create a Razorpay order for a product. Requires product_id, buyer_name, and buyer_address.",
            "parameters": {
                "type": "object",
                "properties": {
                    "product_id": {
                        "type": "string",
                        "description": "The product ID to order"
                    },
                    "buyer_name": {
                        "type": "string",
                        "description": "Name of the buyer"
                    },
                    "buyer_address": {
                        "type": "string",
                        "description": "Delivery address"
                    }
                },
                "required": ["product_id", "buyer_name", "buyer_address"]
            }
        }
    }
]

def execute_tool(tool_name: str, arguments: dict) -> dict:
    """Execute a tool by name with given arguments."""
    if tool_name == "search_catalog":
        return {"products": search_catalog(
            arguments["query"],
            max_price=arguments.get("max_price"),
            gender=arguments.get("gender")
        )}
    elif tool_name == "check_stock":
        return check_stock(arguments["product_id"])
    elif tool_name == "create_order":
        return create_order(
            arguments["product_id"],
            arguments["buyer_name"],
            arguments["buyer_address"]
        )
    return {"error": "unknown_tool"}
