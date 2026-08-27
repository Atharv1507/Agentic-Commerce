import json
import logging
import os
from pathlib import Path
from typing import Any

from fastapi import FastAPI, HTTPException
from pydantic import BaseModel
from openai import OpenAI
from dotenv import load_dotenv

from config import (
    SYSTEM_PROMPT,
    OPENAI_MODEL,
    PERSONAL_AGENT_PORT,
    SESSION_HISTORY_LIMIT,
    SESSIONS_FILE,
)
from schemas import TOOLS_SCHEMA
from handlers import execute_tool

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

load_dotenv()

app = FastAPI(title="Personal Agent")

openai_client = OpenAI(api_key=os.getenv("OPENAI_API_KEY"))


def load_sessions() -> dict[str, Any]:
    """Load sessions from JSON file."""
    if SESSIONS_FILE.exists():
        with open(SESSIONS_FILE, "r") as f:
            return json.load(f)
    return {}


def save_sessions(sessions: dict[str, Any]) -> None:
    """Save sessions to JSON file."""
    with open(SESSIONS_FILE, "w") as f:
        json.dump(sessions, f, indent=2)


sessions = load_sessions()


class OnboardingRequest(BaseModel):
    """Request model for onboarding endpoint."""

    email: str
    phone: str
    address: str
    gender: str
    payment_method: str


class ChatRequest(BaseModel):
    """Request model for chat endpoint."""

    email: str
    text: str


@app.post("/onboarding")
async def onboarding(request: OnboardingRequest) -> dict[str, Any]:
    """Create or update user session with onboarding details.

    Args:
        request: OnboardingRequest with user details.

    Returns:
        Dict with session status and greeting.
    """
    email = request.email.lower()

    sessions[email] = {
        "user": {
            "email": email,
            "phone": request.phone,
            "address": request.address,
            "gender": request.gender,
            "payment_method": request.payment_method,
        },
        "preferences": {},
        "cart": [],
        "history": [],
    }

    save_sessions(sessions)
    logger.info(f"Session created for {email}")

    return {
        "status": "ok",
        "message": "What can I help you find?",
    }


@app.get("/session/{email}")
async def get_session(email: str) -> dict[str, Any]:
    """Get stored session for a user.

    Args:
        email: User's email address.

    Returns:
        Dict with session data or error.
    """
    email = email.lower()

    if email not in sessions:
        raise HTTPException(status_code=404, detail="Session not found")

    session = sessions[email]
    return {
        "status": "ok",
        "user": session["user"],
        "preferences": session["preferences"],
        "cart": session["cart"],
        "history": session["history"],
    }


@app.post("/chat")
async def chat(request: ChatRequest) -> dict[str, Any]:
    """Handle user chat message.

    Args:
        request: ChatRequest with email and message text.

    Returns:
        Dict with agent response.
    """
    email = request.email.lower()

    if email not in sessions:
        raise HTTPException(status_code=404, detail="Session not found. Please complete onboarding.")

    session = sessions[email]
    session["history"].append({"role": "user", "content": request.text})

    messages = [{"role": "system", "content": SYSTEM_PROMPT}]

    history = session["history"][-SESSION_HISTORY_LIMIT:]
    if history and history[0].get("role") == "tool":
        history = history[1:]
    messages.extend(history)

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

                result = execute_tool(function_name, arguments, session)
                all_tool_results.append(
                    {
                        "tool_call_id": tool_call.id,
                        "tool": function_name,
                        "result": result,
                    }
                )

            session["history"].append(
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
                session["history"].append(
                    {
                        "role": "tool",
                        "tool_call_id": tr["tool_call_id"],
                        "content": json.dumps(tr["result"]),
                    }
                )

            num_tool_calls = len(assistant_message.tool_calls)

            response = openai_client.chat.completions.create(
                model=OPENAI_MODEL,
                messages=[{"role": "system", "content": SYSTEM_PROMPT}]
                + session["history"][-SESSION_HISTORY_LIMIT:],
                tools=TOOLS_SCHEMA,
                tool_choice="auto",
            )
            assistant_message = response.choices[0].message

            for tr in all_tool_results[-num_tool_calls :]:
                if tr["tool"] == "message_seller":
                    seller_response = tr["result"].get("response", "")
                    if seller_response:
                        logger.info(f"Seller response: {seller_response[:100]}...")

        final_message = assistant_message.content
        session["history"].append({"role": "assistant", "content": final_message})

        save_sessions(sessions)

        return {"response": final_message, "tool_results": all_tool_results}

    except Exception as e:
        logger.error(f"Error: {e}")
        return {
            "response": "I'm having trouble processing your request. Please try again.",
            "tool_results": [],
        }


@app.get("/health")
async def health() -> dict[str, Any]:
    """Health check endpoint."""
    return {"status": "ok", "active_sessions": len(sessions)}


if __name__ == "__main__":
    import uvicorn

    uvicorn.run(app, host="0.0.0.0", port=PERSONAL_AGENT_PORT)
