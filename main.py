import json
import logging
import os
from typing import Any

from fastapi import FastAPI
from pydantic import BaseModel
from openai import OpenAI
from dotenv import load_dotenv

from config import SYSTEM_PROMPT, OPENAI_MODEL, SELLER_AGENT_PORT, SESSION_HISTORY_LIMIT
from schemas import TOOLS_SCHEMA
from handlers import execute_tool

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

load_dotenv()

app = FastAPI(title="Seller Agent")

openai_client = OpenAI(api_key=os.getenv("OPENAI_API_KEY"))

sessions: dict[str, list[dict[str, Any]]] = {}


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
    messages.extend(sessions[session_id][-SESSION_HISTORY_LIMIT:])

    try:
        response = openai_client.chat.completions.create(
            model=OPENAI_MODEL,
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
                model=OPENAI_MODEL,
                messages=[{"role": "system", "content": SYSTEM_PROMPT}]
                + sessions[session_id][-SESSION_HISTORY_LIMIT:],
                tools=TOOLS_SCHEMA,
                tool_choice="auto",
            )
            assistant_message = response.choices[0].message

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
    """Health check endpoint."""
    return {"status": "ok", "active_sessions": len(sessions)}


if __name__ == "__main__":
    import uvicorn

    uvicorn.run(app, host="0.0.0.0", port=SELLER_AGENT_PORT)
