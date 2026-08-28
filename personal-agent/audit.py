"""Per-shopper audit trail: a bounded, human-readable record of every tool call.

Tool calls were previously only visible via `logging` (stdout), which
disappears the moment the demo terminal scrolls. This module turns each call
into a small persisted entry — timestamp, tool name, a one-line explanation,
and compacted input/output — so `/session/{email}/logs` (see main.py) can show
a real "why did the agent do that" trail for money-relevant actions like
checkout_cart and verify_payment, not just search results.

Explanations are read from strings the tools already write for the model
(`note`, `message`, `shortfall`, ...) rather than invented here — those are
already the carefully-worded, accurate explanation of what happened.
"""

import logging
import time
from typing import Any, Callable

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Kept per session rather than centralised in config.py, next to the code that
# enforces it — same convention as MAX_THREADS_PER_USER in main.py.
AUDIT_LOG_LIMIT = 200

# Checked in this order: the first one present and truthy wins. Every tool
# that has something worth explaining already writes one of these for the
# model's benefit, so the audit trail reuses that copy instead of duplicating
# it.
_EXPLANATION_KEYS = (
    "message",
    "note",
    "context_note",
    "shortfall",
    "relaxation_note",
    "material_shortfall",
    "material_note",
    "size_shortfall",
)

# One-line fallback per tool, used only when none of _EXPLANATION_KEYS is
# present in the result (a plain, unremarkable success).
_FALLBACK_SUMMARY: dict[str, Callable[[dict[str, Any], dict[str, Any]], str]] = {
    "find_products": lambda args, result: (
        f"Searched for {args.get('query', 'products')} — {result.get('shown_count', 0)} shown"
    ),
    "ask_preferences": lambda args, result: f"Asked narrowing questions for {args.get('query', 'a request')}",
    "list_options": lambda args, result: f"Listed catalogue options for {args.get('query', 'a request')}",
    "check_availability": lambda args, result: "Checked size availability for items on screen",
    "ask_user": lambda args, result: f"Asked the shopper: {args.get('question', '')}"[:200],
    "add_to_cart": lambda args, result: f"Added {len(result.get('added', []))} item(s) to cart",
    "update_cart": lambda args, result: "Updated a cart line",
    "checkout_cart": lambda args, result: (
        f"Order created: {result.get('order_id')} for Rs {result.get('amount_inr', 0):,}"
        if result.get("order_id")
        else "Checkout attempted"
    ),
    "update_profile": lambda args, result: f"Saved profile field(s): {', '.join(args.keys()) or 'none'}",
    "save_preferences": lambda args, result: f"Saved preference(s): {', '.join(args.keys()) or 'none'}",
    "clear_preferences": lambda args, result: f"Cleared preference(s): {', '.join(result.get('cleared', [])) or 'none'}",
    "verify_payment": lambda args, result: (
        f"Payment {result.get('status', 'unknown')} for order {result.get('order_id', args.get('order_id'))}"
    ),
}


def _summarize(tool_name: str, arguments: dict[str, Any], result: dict[str, Any]) -> str:
    """One human-readable line explaining what a tool call actually did."""
    for key in _EXPLANATION_KEYS:
        value = result.get(key)
        if value:
            return str(value)

    if result.get("error"):
        return f"{tool_name} failed: {result['error']}"

    fallback = _FALLBACK_SUMMARY.get(tool_name)
    if fallback:
        try:
            return fallback(arguments, result)
        except Exception:
            pass

    return f"Called {tool_name}"


def _compact(value: Any, max_items: int = 5, max_str: int = 240) -> Any:
    """Trim a tool's raw input/output down to something worth persisting.

    A product record's `image` is a multi-kilobyte data URI that explains
    nothing to an auditor and would balloon sessions.json — dropped outright,
    the same call `build_session_context` already makes for cart rendering.
    Lists (e.g. `products`) are capped so one search result doesn't dominate
    the whole log; long strings are truncated rather than wrapped or escaped.
    """
    if isinstance(value, dict):
        return {k: _compact(v, max_items, max_str) for k, v in value.items() if k != "image"}
    if isinstance(value, list):
        trimmed = [_compact(v, max_items, max_str) for v in value[:max_items]]
        if len(value) > max_items:
            trimmed.append(f"...({len(value) - max_items} more)")
        return trimmed
    if isinstance(value, str) and len(value) > max_str:
        return value[:max_str] + "…"
    return value


def record(
    session: dict[str, Any],
    thread: dict[str, Any],
    tool_name: str,
    arguments: dict[str, Any],
    result: dict[str, Any],
) -> None:
    """Append one audit entry for this tool call, bounded to AUDIT_LOG_LIMIT.

    Args:
        session: The shopper's account-level session — the log lives here so
            it is scoped per-shopper, matching how cart/preferences/threads
            already work, and persists via the existing sessions.json
            save/load path with no extra wiring.
        thread: The active conversation, for the thread_id an entry belongs to.
        tool_name: Name of the tool that was called.
        arguments: The arguments it was called with.
        result: What it returned.
    """
    log = session.setdefault("audit_log", [])
    log.append(
        {
            "timestamp": time.time(),
            "thread_id": thread.get("id"),
            "tool": tool_name,
            "summary": _summarize(tool_name, arguments, result),
            "input": _compact(arguments),
            "output": _compact(result),
        }
    )
    if len(log) > AUDIT_LOG_LIMIT:
        del log[: len(log) - AUDIT_LOG_LIMIT]
