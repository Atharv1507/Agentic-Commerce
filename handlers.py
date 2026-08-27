import os
import logging
from typing import Any, Optional

import httpx
import razorpay
from dotenv import load_dotenv

from config import SELLER_AGENT_URL

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

load_dotenv()

razorpay_client = razorpay.Client(
    auth=(os.getenv("RAZORPAY_KEY_ID"), os.getenv("RAZORPAY_KEY_SECRET"))
)


def message_seller(text: str, session_id: str) -> dict[str, Any]:
    """Send free-text message to Seller Agent.

    Args:
        text: Message to send to Seller Agent.
        session_id: Session ID for Seller Agent context.

    Returns:
        Dict with Seller Agent response.
    """
    try:
        with httpx.Client(timeout=60.0) as client:
            response = client.post(
                f"{SELLER_AGENT_URL}/message",
                json={"session_id": session_id, "text": text},
            )
            response.raise_for_status()
            result = response.json()
            logger.info(f"Seller Agent response: {result.get('response', '')[:100]}...")
            return result
    except httpx.TimeoutException:
        logger.error("Seller Agent timeout")
        return {"response": "Seller is unavailable. Please try again shortly.", "tool_results": []}
    except Exception as e:
        logger.error(f"Seller Agent error: {e}")
        return {"response": "Seller is unavailable. Please try again shortly.", "tool_results": []}


def ask_user(question: str, options: Optional[list[str]] = None) -> dict[str, Any]:
    """Surface a clarifying question to the user.

    Args:
        question: The question to ask.
        options: Optional list of quick-reply options.

    Returns:
        Dict with question and options for frontend rendering.
    """
    logger.info(f"Asking user: {question}")
    return {
        "type": "question",
        "question": question,
        "options": options or []
    }


def pay_order(
    product_ids: list[str],
    amount: int,
    buyer_name: str,
    buyer_email: str,
    buyer_phone: str,
    buyer_address: str,
) -> dict[str, Any]:
    """Create Razorpay order for multiple products.

    Args:
        product_ids: List of product IDs to order.
        amount: Total amount in INR.
        buyer_name: Name of the buyer.
        buyer_email: Email of the buyer.
        buyer_phone: Phone of the buyer.
        buyer_address: Delivery address.

    Returns:
        Dict with order details or error.
    """
    try:
        order = razorpay_client.order.create(
            {
                "amount": amount * 100,
                "currency": "INR",
                "receipt": f"receipt_{'_'.join(product_ids[:3])}",
            }
        )

        logger.info(f"Order created: {order['id']} for products: {product_ids}")
        return {
            "order_id": order["id"],
            "amount": order["amount"],
            "currency": order["currency"],
            "product_ids": product_ids,
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


def execute_tool(tool_name: str, arguments: dict[str, Any], session: dict[str, Any]) -> dict[str, Any]:
    """Execute a tool by name with given arguments.

    Args:
        tool_name: Name of the tool to execute.
        arguments: Tool arguments.
        session: Current user session for context.

    Returns:
        Tool execution result.
    """
    logger.info(f"Executing tool: {tool_name}")

    if tool_name == "message_seller":
        seller_session_id = session.get("email", "default")
        return message_seller(arguments["text"], seller_session_id)
    elif tool_name == "ask_user":
        return ask_user(arguments["question"], arguments.get("options"))
    elif tool_name == "pay_order":
        user = session.get("user", {})
        return pay_order(
            product_ids=arguments["product_ids"],
            amount=arguments["amount"],
            buyer_name=user.get("name", arguments.get("buyer_name", "")),
            buyer_email=user.get("email", arguments.get("buyer_email", "")),
            buyer_phone=user.get("phone", arguments.get("buyer_phone", "")),
            buyer_address=user.get("address", arguments.get("buyer_address", "")),
        )

    logger.error(f"Unknown tool: {tool_name}")
    return {"error": "unknown_tool"}
