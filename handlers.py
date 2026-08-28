import os
import logging
from typing import Any

import razorpay
from dotenv import load_dotenv

from rag import available_sizes, search_catalog, get_product_by_id, price_range
from vocab import SIZES, canonical_size

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

load_dotenv()

razorpay_client = razorpay.Client(
    auth=(os.getenv("RAZORPAY_KEY_ID"), os.getenv("RAZORPAY_KEY_SECRET"))
)


def check_stock(product_id: str, size: Optional[str] = None) -> dict[str, Any]:
    """Report real per-size availability for a product.

    Args:
        product_id: The product ID to check.
        size: Optional size to answer about specifically. Any spelling works
            ("large", "L", "size l").

    Returns:
        Dict with the per-size counts and, when a size was named, whether that
        particular size can be bought. `in_stock` always answers the question
        that was actually asked — for a size-specific check it is about that
        size, not about the product in general, because "yes it's in stock"
        followed by "sorry, not in your size" is the failure this replaces.
    """
    product = get_product_by_id(product_id)
    if not product:
        logger.warning(f"Product not found: {product_id}")
        return {"error": "product_not_found"}

    counts = product["sizes"]
    in_size = available_sizes(product)
    total = sum(counts.values())

    result: dict[str, Any] = {
        "product_id": product_id,
        "name": product["name"],
        "sizes": counts,
        "available_sizes": in_size,
        "total_units": total,
        "in_stock": bool(in_size),
    }

    wanted = canonical_size(size)
    if size and not wanted:
        result["size_note"] = (
            f"'{size}' is not a size this shop uses. Sizes are {', '.join(SIZES)}."
        )
        return result

    if wanted:
        count = counts.get(wanted, 0)
        result["requested_size"] = wanted
        result["requested_size_count"] = count
        result["in_stock"] = count > 0
        if count == 0:
            # Spelled out as an instruction, not just data: an LLM handed
            # `{"L": 0}` alongside `in_stock` for the product as a whole has
            # repeatedly read it as a yes.
            result["size_unavailable"] = (
                f"This product is NOT available in {wanted}. "
                + (
                    f"It is in stock in {', '.join(in_size)}."
                    if in_size
                    else "It is sold out in every size."
                )
                + " Say so plainly — do not offer it in a size the buyer did not ask for "
                  "as though it were what they wanted, and do not create an order for it."
            )

    logger.info(f"Stock check {product_id} size={wanted or 'any'}: {result['in_stock']}")
    return result


def create_order(
    product_ids: list[str],
    buyer_name: str,
    buyer_address: str,
    buyer_email: str,
    buyer_phone: str,
    sizes: Optional[dict[str, str]] = None,
    buyer_size: Optional[str] = None,
) -> dict[str, Any]:
    """Create a Razorpay order for multiple products, in the buyer's sizes.

    Size is validated here and not only at search time. Between a shopper
    seeing a product and paying for it, the size they want can be the one thing
    that doesn't hold — and taking money for a garment that cannot ship is a
    worse failure than refusing the order.

    Args:
        product_ids: List of product IDs to order.
        buyer_name: Name of the buyer.
        buyer_address: Delivery address.
        buyer_email: Email of the buyer.
        buyer_phone: Phone of the buyer.
        sizes: Optional per-product size, keyed by product ID.
        buyer_size: Fallback size for any product `sizes` doesn't cover —
            normally the buyer's usual size from their profile.

    Returns:
        Dict with order details, or an error naming the product and the sizes
        it can actually be had in.
    """
    products = []
    total_amount = 0
    sizes = sizes or {}
    fallback_size = canonical_size(buyer_size)
    ordered_sizes: dict[str, str] = {}

    for pid in product_ids:
        product = get_product_by_id(pid)
        if not product:
            logger.warning(f"Product not found for order: {pid}")
            return {"error": "product_not_found", "product_id": pid}

        wanted = canonical_size(sizes.get(pid)) or fallback_size
        stock = check_stock(pid, wanted)
        if stock.get("error"):
            return {"error": "product_not_found", "product_id": pid}
        if not stock.get("in_stock"):
            logger.warning(f"Out of stock: {pid} size={wanted or 'any'}")
            return {
                "error": "size_unavailable" if wanted else "out_of_stock",
                "product_id": pid,
                "product_name": product["name"],
                "requested_size": wanted,
                "available_sizes": stock.get("available_sizes", []),
                "message": (
                    f"{product['name']} is not available in {wanted}. "
                    + (
                        f"Available sizes: {', '.join(stock['available_sizes'])}."
                        if stock.get("available_sizes")
                        else "It is sold out entirely."
                    )
                    if wanted
                    else f"{product['name']} is sold out in every size."
                ),
            }

        if wanted:
            ordered_sizes[pid] = wanted
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
            "sizes": ordered_sizes,
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
            size=arguments.get("size"),
            exclude_ids=arguments.get("exclude_ids"),
        )
        # Echoing the constraints back lets the Personal Agent verify what was
        # actually applied rather than trusting that its brief survived the
        # trip through this agent's tool-call reasoning.
        return {
            "products": products,
            "applied_constraints": {
                k: arguments.get(k)
                for k in ("max_price", "min_price", "target_price", "gender", "colors", "materials", "brands", "size")
                if arguments.get(k)
            },
        }
    elif tool_name == "price_range":
        return price_range(arguments["query"], gender=arguments.get("gender"))
    elif tool_name == "check_stock":
        return check_stock(arguments["product_id"], arguments.get("size"))
    elif tool_name == "create_order":
        return create_order(
            arguments["product_ids"],
            arguments["buyer_name"],
            arguments["buyer_address"],
            arguments["buyer_email"],
            arguments["buyer_phone"],
            sizes=arguments.get("sizes"),
            buyer_size=arguments.get("buyer_size"),
        )

    logger.error(f"Unknown tool: {tool_name}")
    return {"error": "unknown_tool"}
