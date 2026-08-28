import os
import logging
from typing import Any

import razorpay
from dotenv import load_dotenv

from rag import search_catalog, get_product_by_id, price_range

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

load_dotenv()

razorpay_client = razorpay.Client(
    auth=(os.getenv("RAZORPAY_KEY_ID"), os.getenv("RAZORPAY_KEY_SECRET"))
)


def check_stock(product_id: str) -> dict[str, Any]:
    """Check stock availability for a product.

    Args:
        product_id: The product ID to check.

    Returns:
        Dict with stock status or error.
    """
    product = get_product_by_id(product_id)
    if not product:
        logger.warning(f"Product not found: {product_id}")
        return {"error": "product_not_found"}

    logger.info(f"Stock check for {product_id}: in_stock=True")
    return {"product_id": product_id, "in_stock": True, "stock_count": 10}


def create_order(
    product_ids: list[str],
    buyer_name: str,
    buyer_address: str,
    buyer_email: str,
    buyer_phone: str,
) -> dict[str, Any]:
    """Create a Razorpay order for multiple products.

    Args:
        product_ids: List of product IDs to order.
        buyer_name: Name of the buyer.
        buyer_address: Delivery address.
        buyer_email: Email of the buyer.
        buyer_phone: Phone of the buyer.

    Returns:
        Dict with order details or error.
    """
    products = []
    total_amount = 0

    for pid in product_ids:
        product = get_product_by_id(pid)
        if not product:
            logger.warning(f"Product not found for order: {pid}")
            return {"error": "product_not_found", "product_id": pid}

        stock = check_stock(pid)
        if stock.get("error") or not stock.get("in_stock"):
            logger.warning(f"Out of stock: {pid}")
            return {"error": "out_of_stock", "product_id": pid}

        products.append(product)
        total_amount += product["price"]

    try:
        order = razorpay_client.order.create(
            {
                "amount": total_amount * 100,
                "currency": "INR",
                "receipt": f"receipt_{'_'.join(product_ids[:3])}",
            }
        )

        logger.info(f"Order created: {order['id']} for {len(product_ids)} products")
        return {
            "order_id": order["id"],
            "amount": order["amount"],
            "currency": order["currency"],
            "products": products,
            "buyer": {
                "name": buyer_name,
                "email": buyer_email,
                "phone": buyer_phone,
                "address": buyer_address,
            },
        }
    except Exception as e:
        logger.error(f"Razorpay error: {e}")
        return {"error": "order_creation_failed"}


def execute_tool(tool_name: str, arguments: dict[str, Any]) -> dict[str, Any]:
    """Execute a tool by name with given arguments.

    Args:
        tool_name: Name of the tool to execute.
        arguments: Tool arguments.

    Returns:
        Tool execution result.
    """
    logger.info(f"Executing tool: {tool_name}")

    if tool_name == "search_catalog":
        products = search_catalog(
            arguments["query"],
            top_k=arguments.get("top_k") or 5,
            max_price=arguments.get("max_price"),
            min_price=arguments.get("min_price"),
            target_price=arguments.get("target_price"),
            gender=arguments.get("gender"),
            colors=arguments.get("colors"),
            materials=arguments.get("materials"),
            brands=arguments.get("brands"),
            exclude_ids=arguments.get("exclude_ids"),
        )
        # Echoing the constraints back lets the Personal Agent verify what was
        # actually applied rather than trusting that its brief survived the
        # trip through this agent's tool-call reasoning.
        return {
            "products": products,
            "applied_constraints": {
                k: arguments.get(k)
                for k in ("max_price", "min_price", "target_price", "gender", "colors", "materials", "brands")
                if arguments.get(k)
            },
        }
    elif tool_name == "price_range":
        return price_range(arguments["query"], gender=arguments.get("gender"))
    elif tool_name == "check_stock":
        return check_stock(arguments["product_id"])
    elif tool_name == "create_order":
        return create_order(
            arguments["product_ids"],
            arguments["buyer_name"],
            arguments["buyer_address"],
            arguments["buyer_email"],
            arguments["buyer_phone"],
        )

    logger.error(f"Unknown tool: {tool_name}")
    return {"error": "unknown_tool"}
