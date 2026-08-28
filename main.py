import json
import logging
import os
from typing import Any, Optional

from fastapi import FastAPI
from pydantic import BaseModel
from openai import OpenAI
from dotenv import load_dotenv

from config import (
    SYSTEM_PROMPT,
    OPENAI_MODEL,
    SELLER_AGENT_PORT,
    SESSION_HISTORY_LIMIT,
    MAX_TOOL_ITERATIONS,
)
from schemas import TOOLS_SCHEMA
from handlers import execute_tool
from rag import catalog_facets

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

load_dotenv()

app = FastAPI(title="Seller Agent")

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

    history = _touch_session(session_id)
    history.append({"role": "user", "content": request.text})

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

            for tool_call in assistant_message.tool_calls:
                arguments = json.loads(tool_call.function.arguments or "{}")
                result = execute_tool(tool_call.function.name, arguments)

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


@app.delete("/session/{session_id}")
async def delete_session(session_id: str) -> dict[str, Any]:
    """Forget a negotiation's history once the buyer's agent is done with it.

    Args:
        session_id: The negotiation session to drop.

    Returns:
        Dict with status.
    """
    existed = _drop_session(session_id)
    return {"status": "ok", "deleted": existed}


class FacetsRequest(BaseModel):
    """Request model for /facets endpoint."""

    query: str
    gender: Optional[str] = None
    full: bool = False


@app.post("/facets")
async def facets(request: FacetsRequest) -> dict[str, Any]:
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


@app.get("/health")
async def health() -> dict[str, Any]:
    """Health check endpoint."""
    return {"status": "ok", "active_sessions": len(sessions)}


if __name__ == "__main__":
    import uvicorn

    uvicorn.run(app, host="0.0.0.0", port=SELLER_AGENT_PORT)
