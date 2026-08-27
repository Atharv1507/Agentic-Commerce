import json
import logging
import os
from typing import Any

from fastapi import FastAPI
from pydantic import BaseModel
from openai import OpenAI
from dotenv import load_dotenv

from tools import TOOLS_SCHEMA, execute_tool

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

load_dotenv()

app = FastAPI(title="Seller Agent")

openai_client = OpenAI(api_key=os.getenv("OPENAI_API_KEY"))

sessions: dict[str, list[dict[str, Any]]] = {}

SYSTEM_PROMPT = """You are a merchant assistant for a shoe store. You help find products, check stock, and create orders.

You have 3 tools:
1. search_catalog(query, max_price?, gender?) - Search products by natural language with optional filters
2. check_stock(product_id) - Check if a product is in stock
3. create_order(product_id, buyer_name, buyer_address) - Create a Razorpay order

WORKFLOW FOR ORDERS:
When user wants to buy a product:
1. FIRST call check_stock to verify availability
2. IF in stock, IMMEDIATELY call create_order with the product_id, buyer_name, and buyer_address
3. DO NOT stop after check_stock - you MUST call create_order if in stock
4. ONLY if out of stock, inform the user

RULES:
- If the message mentions a budget/price limit → USE the max_price parameter in search_catalog
- If the message specifies gender → USE the gender parameter in search_catalog
- If the message is about finding/searching products → call search_catalog
- If the message mentions buying/ordering with all details (product_id, buyer_name, address) → call check_stock THEN create_order
- If information is missing to call a tool (e.g., no buyer name/address for order), ask for it
- If no products match the query, say "No products fit your description" - do NOT make up products
- Only show products that match the user's criteria (price, gender, etc.)
- For upsell/cross-sell: after showing main results, suggest 1-2 complementary options if relevant

Response format:
- Always respond in natural language
- Include structured data when showing products (id, name, price, brand)
- Be helpful and concise"""


class MessageRequest(BaseModel):
    """Request model for /message endpoint."""

    session_id: str
    text: str


@app.post("/message")
async def handle_message(request: MessageRequest) -> dict[str, Any]:
    """Handle incoming message from Personal Agent.

    Args:
        request: MessageRequest with session_id and text.

    Returns:
        Dict with response and tool_results.
    """
    session_id = request.session_id

    if session_id not in sessions:
        sessions[session_id] = []

    sessions[session_id].append({"role": "user", "content": request.text})

    messages = [{"role": "system", "content": SYSTEM_PROMPT}]
    messages.extend(sessions[session_id][-20:])

    try:
        response = openai_client.chat.completions.create(
            model="gpt-4o-mini",
            messages=messages,
            tools=TOOLS_SCHEMA,
            tool_choice="auto",
        )

        assistant_message = response.choices[0].message
        all_tool_results: list[dict[str, Any]] = []

        while assistant_message.tool_calls:
            logger.info(
                f"Tool calls: {[tc.function.name for tc in assistant_message.tool_calls]}"
            )

            for tool_call in assistant_message.tool_calls:
                function_name = tool_call.function.name
                arguments = json.loads(tool_call.function.arguments)

                result = execute_tool(function_name, arguments)
                all_tool_results.append(
                    {
                        "tool_call_id": tool_call.id,
                        "tool": function_name,
                        "result": result,
                    }
                )

            sessions[session_id].append(
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

            for tr in all_tool_results[-len(assistant_message.tool_calls) :]:
                sessions[session_id].append(
                    {
                        "role": "tool",
                        "tool_call_id": tr["tool_call_id"],
                        "content": json.dumps(tr["result"]),
                    }
                )

            response = openai_client.chat.completions.create(
                model="gpt-4o-mini",
                messages=[{"role": "system", "content": SYSTEM_PROMPT}]
                + sessions[session_id][-20:],
                tools=TOOLS_SCHEMA,
                tool_choice="auto",
            )
            assistant_message = response.choices[0].message
            logger.info(
                f"After tool call - content: {assistant_message.content[:50] if assistant_message.content else 'None'}..."
            )

        final_message = assistant_message.content
        sessions[session_id].append({"role": "assistant", "content": final_message})

        return {"response": final_message, "tool_results": all_tool_results}

    except Exception as e:
        logger.error(f"Error: {e}")
        return {
            "response": "I'm having trouble processing your request. Please try again.",
            "tool_results": [],
        }


@app.get("/health")
async def health() -> dict[str, int]:
    """Health check endpoint.

    Returns:
        Dict with status and active session count.
    """
    return {"status": "ok", "active_sessions": len(sessions)}


if __name__ == "__main__":
    import uvicorn

    uvicorn.run(app, host="0.0.0.0", port=8001)
