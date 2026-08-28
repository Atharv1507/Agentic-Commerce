import asyncio
import json
import logging
import os
import queue
import threading
import time
from typing import Any, Callable, Optional

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse
from pydantic import BaseModel
from openai import OpenAI
from dotenv import load_dotenv

from config import (
    SYSTEM_PROMPT,
    OPENAI_MODEL,
    PERSONAL_AGENT_PORT,
    SESSION_HISTORY_LIMIT,
    SESSIONS_FILE,
    MAX_TOOL_ITERATIONS,
)
from schemas import TOOLS_SCHEMA
from context import durable_hints, normalize_gender
from handlers import PREFERENCE_FIELDS, execute_tool, extract_structured_payload

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

load_dotenv()

app = FastAPI(title="Personal Agent")

# The React frontend runs on Vite's dev origin (localhost:5173), a different
# origin than this API (localhost:8000) — the browser blocks the fetch calls
# without this. Wide open since this is a local hackathon build, not multi-tenant.
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

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


def build_session_context(session: dict[str, Any], thread: dict[str, Any]) -> str:
    """Render live state for the LLM, keeping the three kinds of state apart.

    DETAILS are account-level facts about the person (address, phone, gender).
    PREFERENCES are account-level taste — a soft hint, never a filter. THIS
    CONVERSATION holds what is being shopped for right now, which is the only
    scope a fabric, a colour-for-this-garment or a budget belongs to.

    Collapsing the last two into one durable blob is what made "linen shirts"
    behave like a permanent filter, so they are labelled and scoped separately
    here — and the conversation scope comes from `thread`, not the account, so a
    different chat cannot see it at all.

    Empty-string profile fields are dropped so the model can tell what's
    actually known versus what's missing (an empty string must not look
    like known data).
    """
    user = {k: v for k, v in session.get("user", {}).items() if v and k != "gender_normalized"}
    preferences = durable_hints(session.get("preferences") or {})
    cart = session.get("cart", [])
    seen_count = len(thread.get("seen_product_ids") or [])

    lines = [
        "SESSION CONTEXT (live, do not ask the user for anything listed here as already known):",
        f"User details (account-level, never a search filter except gender): "
        f"{json.dumps(user) if user else '{} (nothing known yet)'}",
    ]

    gender = normalize_gender(session.get("user", {}).get("gender"))
    if gender:
        lines.append(
            f"Gender for search: {gender}. This is applied to every search automatically — "
            f"you do not need to pass it, and you must not ask about it."
        )

    if preferences:
        lines.append(
            f"Saved preferences (account-level taste, a SOFT default only): {json.dumps(preferences)}. "
            f"Anything the shopper says this turn overrides these. If they say they have no "
            f"preference, these are ignored entirely for that search."
        )
    else:
        lines.append("Saved preferences: none.")

    subject = thread.get("subject_query")
    if subject:
        active = thread.get("subject_constraints") or {}
        lines.append(
            f"THIS CONVERSATION is currently about: {subject}"
            + (f" with constraints {json.dumps(active)}." if active else ".")
            + " Those constraints belong to this product type ONLY. The moment the shopper "
              "asks for a different product type, they are gone — do not re-send them, do "
              "not mention the old product, and do not report a shortfall about it."
        )

    lines.append(f"Current cart: {json.dumps(cart) if cart else 'empty'}")
    if seen_count:
        lines.append(
            f"{seen_count} product(s) have already been shown in this conversation; "
            f"find_products excludes them automatically, so results will be genuinely new."
        )

    return "\n".join(lines)


def trimmed_history(history: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Take the tail of the conversation without orphaning tool messages.

    A `tool` message is only valid when the assistant message that requested it
    is also present. Slicing a fixed-size window can cut that assistant message
    away and leave its tool replies stranded at the front, which the API rejects
    outright — so drop any leading tool messages the window exposes.
    """
    window = history[-SESSION_HISTORY_LIMIT:]
    start = 0
    while start < len(window) and window[start].get("role") == "tool":
        start += 1
    return window[start:]


def build_messages(session: dict[str, Any], thread: dict[str, Any]) -> list[dict[str, Any]]:
    """Assemble the message list for one model call."""
    return [
        {
            "role": "system",
            "content": SYSTEM_PROMPT + "\n\n" + build_session_context(session, thread),
        }
    ] + trimmed_history(thread["history"])


def run_chat_turn(
    session: dict[str, Any],
    thread: dict[str, Any],
    text: str,
    emit: Optional[Callable[[str, dict[str, Any]], None]] = None,
) -> dict[str, Any]:
    """Run one complete user turn: model calls, tool calls, final reply.

    Args:
        session: The user's account-level session, mutated in place.
        thread: The active conversation, mutated in place. History and shopping
            subject live here so two chats never see each other's context.
        text: The user's message.
        emit: Optional progress callback, forwarded into long-running tools.

    Returns:
        The response payload for the frontend.
    """
    def progress(stage: str, **payload: Any) -> None:
        if emit:
            emit(stage, payload)

    thread["history"].append({"role": "user", "content": text})
    thread["updated_at"] = time.time()
    all_tool_results: list[dict[str, Any]] = []
    final_message: Optional[str] = None

    progress("thinking")

    for _ in range(MAX_TOOL_ITERATIONS):
        response = openai_client.chat.completions.create(
            model=OPENAI_MODEL,
            messages=build_messages(session, thread),
            tools=TOOLS_SCHEMA,
            tool_choice="auto",
        )
        assistant_message = response.choices[0].message

        if not assistant_message.tool_calls:
            final_message = assistant_message.content
            break

        logger.info(f"Tool calls: {[tc.function.name for tc in assistant_message.tool_calls]}")

        thread["history"].append(
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
            result = execute_tool(
                tool_call.function.name, arguments, session, thread, turn_text=text, emit=emit
            )

            all_tool_results.append(
                {
                    "tool_call_id": tool_call.id,
                    "tool": tool_call.function.name,
                    "result": result,
                }
            )
            thread["history"].append(
                {
                    "role": "tool",
                    "tool_call_id": tool_call.id,
                    "content": json.dumps(result),
                }
            )

    if final_message is None:
        # Iteration budget spent. Ask for prose with tools switched off rather
        # than dropping the turn — the user still gets an answer built on
        # whatever the tools did manage to gather.
        logger.warning("Tool iteration budget exhausted; forcing a text response")
        progress("wrapping_up")
        response = openai_client.chat.completions.create(
            model=OPENAI_MODEL,
            messages=build_messages(session, thread),
            tools=TOOLS_SCHEMA,
            tool_choice="none",
        )
        final_message = response.choices[0].message.content

    thread["history"].append({"role": "assistant", "content": final_message})

    structured = extract_structured_payload(all_tool_results)
    payload = {
        "response": final_message,
        "tool_results": all_tool_results,
        "products": structured["products"],
        "complements": structured["complements"],
        "options": structured["options"],
        "form": structured["form"],
    }
    if structured["profile_dirty"]:
        # Details or preferences changed during the turn (typically an address
        # given at checkout). Hand the fresh copy back so the frontend's
        # Settings reflect it without the shopper re-typing anything.
        payload["profile"] = session.get("user", {})
        payload["preferences"] = durable_hints(session.get("preferences") or {})
    return payload


class OnboardingRequest(BaseModel):
    """Request model for onboarding endpoint."""

    email: str
    phone: str
    address: str
    gender: str
    payment_method: str
    name: Optional[str] = None


class ChatRequest(BaseModel):
    """Request model for chat endpoint."""

    email: str
    text: str
    # Which conversation this message belongs to. Defaults so an older client
    # (or a curl call) still works, it just shares one thread.
    thread_id: Optional[str] = None


@app.post("/onboarding")
async def onboarding(request: OnboardingRequest) -> dict[str, Any]:
    """Create a session, or update the profile on an existing one.

    The frontend also posts here when the user edits their details in Settings,
    so this merges into any existing session instead of replacing it —
    rebuilding the dict wholesale used to wipe the user's cart, learned
    preferences, and conversation history on every profile save.

    Args:
        request: OnboardingRequest with user details.

    Returns:
        Dict with session status and greeting.
    """
    email = request.email.lower()

    session = _migrate_session(
        sessions.setdefault(email, {"user": {}, "preferences": {}, "cart": [], "threads": {}})
    )
    details = {
        "email": email,
        "phone": request.phone,
        "address": request.address,
        "gender": request.gender,
        "payment_method": request.payment_method,
        "gender_normalized": normalize_gender(request.gender),
    }
    if request.name:
        details["name"] = request.name
    # Blank fields mean "not answered yet" (onboarding is skippable), so they
    # must not overwrite a detail the shopper already gave — including one the
    # agent collected mid-chat at checkout.
    session["user"].update({k: v for k, v in details.items() if v or k == "email"})

    save_sessions(sessions)
    logger.info(f"Session saved for {email}")

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

    session = _require_session(email)
    return {
        "status": "ok",
        "user": session["user"],
        "preferences": durable_hints(session.get("preferences") or {}),
        "cart": session.get("cart", []),
        "threads": {
            key: {"messages": len(t.get("history") or []), "subject": t.get("subject_query")}
            for key, t in (session.get("threads") or {}).items()
        },
    }


@app.post("/session/{email}/reset-history")
async def reset_history(email: str, body: Optional[dict[str, Any]] = None) -> dict[str, Any]:
    """Clear one conversation's context without touching the account.

    Scoped to a single thread now that the agent keeps one history per chat:
    resetting used to wipe the account's only history, which is why switching
    chats had to throw away context that the shopper could still see on screen.

    Details, saved preferences, and the cart are left intact — this only clears
    what belongs to the conversation: its transcript, its shopping subject, and
    its already-shown products (a fresh chat should be free to surface the best
    matches again).

    Args:
        email: User's email address.
        body: Optional {"thread_id": ...}. Omitted means the default thread.

    Returns:
        Dict with status, or 404 if the session doesn't exist.
    """
    email = email.lower()
    session = _require_session(email)
    thread = _require_thread(session, (body or {}).get("thread_id"))

    thread["history"] = []
    thread["seen_product_ids"] = []
    thread.pop("subject_query", None)
    thread.pop("subject_tokens", None)
    thread.pop("subject_constraints", None)
    thread.pop("last_primary_tokens", None)

    save_sessions(sessions)
    logger.info(f"Conversation {thread['id']} reset for {email}")

    return {"status": "ok", "thread_id": thread["id"]}


@app.delete("/session/{email}/thread/{thread_id}")
async def delete_thread(email: str, thread_id: str) -> dict[str, Any]:
    """Forget a conversation entirely, because the shopper deleted it.

    Args:
        email: User's email address.
        thread_id: The conversation to drop.

    Returns:
        Dict with status.
    """
    email = email.lower()
    session = _require_session(email)
    existed = session.get("threads", {}).pop(thread_id, None) is not None

    save_sessions(sessions)
    logger.info(f"Conversation {thread_id} deleted for {email} (existed={existed})")

    return {"status": "ok", "deleted": existed}


class PreferencesRequest(BaseModel):
    """Request model for replacing saved preferences from Settings."""

    preferences: dict[str, Any]


@app.get("/session/{email}/preferences")
async def get_preferences(email: str) -> dict[str, Any]:
    """Read the account's saved preferences, so Settings can show them.

    Preferences were previously invisible — learned in chat, applied to every
    later search, and impossible to inspect or remove. Anything that shapes
    results has to be something the shopper can see and delete.
    """
    session = _require_session(email.lower())
    return {"status": "ok", "preferences": durable_hints(session.get("preferences") or {})}


@app.put("/session/{email}/preferences")
async def put_preferences(email: str, request: PreferencesRequest) -> dict[str, Any]:
    """Replace saved preferences with exactly what Settings submitted.

    A replace rather than a merge: the agent's own save path merges, so removal
    would otherwise be impossible from the UI. Unknown keys are dropped, and
    fabric is never accepted — it belongs to a product type, not to a person.
    """
    email = email.lower()
    session = _require_session(email)

    cleaned: dict[str, Any] = {}
    for field in PREFERENCE_FIELDS:
        value = request.preferences.get(field)
        if isinstance(value, list):
            value = [v for v in value if v]
        if value:
            cleaned[field] = value

    session["preferences"] = cleaned
    save_sessions(sessions)
    logger.info(f"Preferences replaced for {email}: {cleaned}")

    return {"status": "ok", "preferences": cleaned}


@app.delete("/session/{email}/preferences")
async def delete_preferences(email: str) -> dict[str, Any]:
    """Clear every saved preference for the account."""
    email = email.lower()
    session = _require_session(email)
    session["preferences"] = {}
    save_sessions(sessions)
    logger.info(f"Preferences cleared for {email}")
    return {"status": "ok", "preferences": {}}


@app.post("/cart/{email}")
async def add_to_cart(email: str, item: dict[str, Any]) -> dict[str, Any]:
    """Add a product to the user's session cart, or bump its quantity.

    Args:
        email: User's email address.
        item: Product dict (id, name, brand, price, color, gender,
            description, optional quantity — defaults to 1).

    Returns:
        Dict with the updated cart.
    """
    email = email.lower()

    if email not in sessions:
        raise HTTPException(status_code=404, detail="Session not found")

    session = sessions[email]
    cart = session["cart"]

    existing = next((entry for entry in cart if entry.get("id") == item.get("id")), None)
    if existing:
        existing["quantity"] = existing.get("quantity", 1) + item.get("quantity", 1)
    else:
        item.setdefault("quantity", 1)
        cart.append(item)

    save_sessions(sessions)
    logger.info(f"Cart updated for {email}: added {item.get('id')}")

    return {"status": "ok", "cart": cart}


@app.delete("/cart/{email}/{product_id}")
async def remove_from_cart(email: str, product_id: str) -> dict[str, Any]:
    """Remove a product from the user's session cart.

    Args:
        email: User's email address.
        product_id: ID of the product to remove.

    Returns:
        Dict with the updated cart.
    """
    email = email.lower()

    if email not in sessions:
        raise HTTPException(status_code=404, detail="Session not found")

    session = sessions[email]
    session["cart"] = [entry for entry in session["cart"] if entry.get("id") != product_id]

    save_sessions(sessions)
    logger.info(f"Cart updated for {email}: removed {product_id}")

    return {"status": "ok", "cart": session["cart"]}


# Conversations kept per account. Old ones are pruned so sessions.json doesn't
# grow forever; the frontend keeps its own copy of the transcript regardless.
MAX_THREADS_PER_USER = 20


def _migrate_session(session: dict[str, Any]) -> dict[str, Any]:
    """Bring a session up to the per-conversation shape.

    Earlier builds kept ONE history and one already-seen list per account, which
    every chat shared — so a new chat either saw the previous chat's context or
    had to wipe it. Both are wrong. Legacy state is folded into a single
    "default" conversation rather than discarded.
    """
    session.setdefault("user", {})
    session.setdefault("preferences", {})
    session.setdefault("cart", [])
    threads = session.setdefault("threads", {})

    legacy_history = session.pop("history", None)
    legacy_seen = session.pop("seen_product_ids", None)
    session.pop("last_primary_tokens", None)
    if legacy_history or legacy_seen:
        threads["default"] = {
            "id": "default",
            "history": legacy_history or [],
            "seen_product_ids": legacy_seen or [],
            "updated_at": time.time(),
        }

    # Fabric was never a durable, account-level taste — drop any that a previous
    # build saved, otherwise the very bug this change fixes survives the upgrade.
    session["preferences"].pop("materials", None)
    return session


def _require_session(email: str) -> dict[str, Any]:
    if email not in sessions:
        raise HTTPException(status_code=404, detail="Session not found. Please complete onboarding.")
    return _migrate_session(sessions[email])


def _require_thread(session: dict[str, Any], thread_id: Optional[str]) -> dict[str, Any]:
    """Get (or open) one conversation within an account's session.

    A thread id comes from the frontend's chat list, so the agent's memory lines
    up exactly with the transcript the shopper is looking at: switching back to
    an old chat restores its context, and a new chat starts genuinely empty
    instead of inheriting whatever the last one was about.
    """
    threads = session.setdefault("threads", {})
    key = thread_id or "default"
    thread = threads.get(key)
    if thread is None:
        thread = {"id": key, "history": [], "seen_product_ids": [], "updated_at": time.time()}
        threads[key] = thread

        if len(threads) > MAX_THREADS_PER_USER:
            oldest = sorted(threads.items(), key=lambda kv: kv[1].get("updated_at") or 0)
            for stale_key, _ in oldest[: len(threads) - MAX_THREADS_PER_USER]:
                if stale_key != key:
                    threads.pop(stale_key, None)

    thread.setdefault("id", key)
    thread.setdefault("history", [])
    thread.setdefault("seen_product_ids", [])
    return thread


FALLBACK_REPLY = "I'm having trouble processing your request. Please try again."


def _error_payload() -> dict[str, Any]:
    return {
        "response": FALLBACK_REPLY,
        "tool_results": [],
        "products": [],
        "complements": [],
        "options": None,
        "form": None,
    }


@app.post("/chat")
async def chat(request: ChatRequest) -> dict[str, Any]:
    """Handle a user chat message and return the complete result.

    Args:
        request: ChatRequest with email and message text.

    Returns:
        Dict with the agent's reply plus structured products/options.
    """
    email = request.email.lower()
    session = _require_session(email)
    thread = _require_thread(session, request.thread_id)

    try:
        payload = run_chat_turn(session, thread, request.text)
        save_sessions(sessions)
        return payload
    except Exception as e:
        logger.error(f"Error: {e}")
        return _error_payload()


def _progress_label(stage: str, data: dict[str, Any]) -> str:
    """Human-readable narration for a progress event.

    Composed here rather than in the browser so the copy stays next to the
    logic that knows what actually happened — these describe real steps of the
    seller negotiation, not a timed animation.
    """
    if stage == "thinking":
        return "Working out what you're after"

    if stage == "seller_round":
        query = data.get("query") or "your request"
        if data.get("round", 1) == 1:
            return f"Asking the seller about {query}"
        return f"Round {data['round']}: pushing the seller for closer matches"

    if stage == "evaluating":
        offered = data.get("offered", 0)
        if not offered:
            return "The seller came back empty — trying a different angle"
        return f"Checking {offered} option(s) against your budget and preferences"

    if stage == "retry":
        return f"Only {data.get('have', 0)} of {data.get('need', 3)} fit — asking the seller again"

    if stage == "resolved":
        if data.get("purpose") == "complement":
            return "Picking something that pairs well"
        found = data.get("found", 0)
        return f"Found {found} that fit" if found else "Nothing here fits those constraints"

    if stage == "wrapping_up":
        return "Putting your answer together"

    return "Working on it"


@app.post("/chat/stream")
async def chat_stream(request: ChatRequest) -> StreamingResponse:
    """Same as /chat, but streams progress events over SSE while it works.

    A turn can involve several rounds of back-and-forth with the Seller Agent,
    which is slow enough that a static spinner reads as a hang. Each event says
    what the agent is genuinely doing right now; the final event carries the
    same payload /chat would have returned.

    Args:
        request: ChatRequest with email and message text.

    Returns:
        A text/event-stream of JSON events, ending with one of type "final".
    """
    email = request.email.lower()
    session = _require_session(email)
    thread = _require_thread(session, request.thread_id)

    events: queue.Queue = queue.Queue()

    def emit(stage: str, payload: dict[str, Any]) -> None:
        events.put({"type": "progress", "stage": stage, "label": _progress_label(stage, payload), **payload})

    def worker() -> None:
        try:
            payload = run_chat_turn(session, thread, request.text, emit=emit)
            save_sessions(sessions)
            events.put({"type": "final", **payload})
        except Exception as e:
            logger.error(f"Error: {e}")
            events.put({"type": "final", **_error_payload()})
        finally:
            events.put(None)

    async def stream():
        # The turn is blocking (sync OpenAI + httpx calls), so it runs on its
        # own thread and hands events back through the queue.
        threading.Thread(target=worker, daemon=True).start()
        loop = asyncio.get_running_loop()
        while True:
            event = await loop.run_in_executor(None, events.get)
            if event is None:
                break
            yield f"data: {json.dumps(event)}\n\n"

    return StreamingResponse(
        stream(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


@app.get("/health")
async def health() -> dict[str, Any]:
    """Health check endpoint."""
    return {"status": "ok", "active_sessions": len(sessions)}


if __name__ == "__main__":
    import uvicorn

    uvicorn.run(app, host="0.0.0.0", port=PERSONAL_AGENT_PORT)
