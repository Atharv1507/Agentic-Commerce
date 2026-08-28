# Personal Agent

The shopper-facing agent. It's the only backend service the frontend talks to
for shopping — everything else (catalogue search, pricing, payments, the
seller's own reasoning) happens behind it. It owns the conversation, the
shopper's profile/cart/preferences, the spend guardrail, and the decision of
when and how hard to push the Seller Agent for better results.

What it deliberately does **not** own: money. It holds no Razorpay credentials
at all. Orders are created and payments verified by the merchant, because the
merchant owns the Razorpay account — an agent representing the *buyer* that
held merchant payment keys wouldn't be a buyer agent, it would be the shop.

## Tech stack

- **FastAPI** + **uvicorn** — HTTP API, run with `python main.py` (port 8000
  by default, `PERSONAL_AGENT_PORT` to override)
- **OpenAI** (`gpt-5-mini` by default, `OPENAI_MODEL` to override) — function
  calling drives every decision: which tool to call, what to say
- **httpx** — synchronous client used to talk to the Seller Agent, presenting
  `X-Buyer-Key` (`SELLER_BUYER_KEY`) on every call
- Persistence is a single flat file, `sessions.json` (one entry per shopper
  email; no database). Written atomically (temp file + `os.replace`) with the
  disk write and fsync on a background thread so a chat reply never blocks
- **No razorpay SDK.** See above

## Flow

1. Frontend posts to `/onboarding` (or skips it) and then `/chat` /
   `/chat/stream` for every message, always with `email` + `thread_id`.
2. `run_chat_turn` (`main.py`) loads that shopper's session and thread, then
   runs an OpenAI tool-calling loop (`MAX_TOOL_ITERATIONS = 6`): call the model
   → if it wants a tool, execute it → feed the result back → repeat until the
   model returns plain text.
3. Tools live in `handlers.py` as plain Python functions, never HTTP endpoints
   of their own. The one that matters most is `find_products`, which hands off
   to `negotiation.py`.
4. `negotiation.py` is where the agent-to-agent commerce happens: it turns the
   shopper's stated constraints (budget, colour, size, fabric…) into a numeric
   band, briefs the Seller Agent over HTTP, and **verifies every returned
   product against the constraints itself** — the seller's prose is never
   trusted. If too few products survive, it tightens the brief and asks again,
   up to `MAX_SELLER_ROUNDS = 3` (`2` for a cross-sell pass).
5. Any live merchant campaign the seller volunteers comes back as structured
   `offers`, passed through in the merchant's own wording. This agent never
   computes, combines or restates a saving — it's the merchant's money and the
   merchant applies the discount at order time regardless.
6. Checkout: `checkout_cart` runs its own gates first (cart non-empty, buyer
   details present, per-size stock pre-check), then the **spend limit**, then
   asks the merchant to create the order.
7. `verify_payment` asks the merchant to confirm with Razorpay, and keeps its
   own idempotency guard so a resent confirmation can't be processed twice.

## Money guardrails

These are code-level, not prompt-level, and that's the point:

- **Spend limit** (`DEFAULT_SPEND_LIMIT`, or per-shopper in Settings) is
  enforced in `checkout_cart` before any network call. `update_profile`
  deliberately cannot write `spend_limit`, so the shopper cannot talk the agent
  into raising their own ceiling.
- **The override is a byte-for-byte phrase match**, checked in `main.py`
  *before the model ever sees the message* — the bypass is an equality check,
  not a judgement call.
- **The limit is re-checked against what the merchant actually charged.** The
  first check uses this agent's cart total; the merchant prices from its own
  live catalogue and may apply a campaign, so the two can legitimately differ.
  A discount is fine. A total *above* what the shopper approved never reaches
  the payment modal.
- **Stock is verified per size before checkout**, each cart line in its own
  size, quantity included.
- **`audit.py`** records every tool call per shopper (bounded to 200), reusing
  the explanation each tool already writes, exposed at `/session/{email}/logs`.
- **Paise vs rupees** is stated explicitly on every amount (`amount_inr` plus
  an `amount_note`) after a real bug where two ₹1,049 shirts were quoted as
  "₹209,800".

## Endpoints

All of these are called directly by the React frontend — no auth, this is a
hackathon build (see the CORS comment in `main.py`).

| Method | Path | Purpose |
|---|---|---|
| POST | `/onboarding` | Create a session, or merge new profile fields into an existing one |
| GET | `/session/{email}` | Read profile, preferences, cart, thread summaries |
| POST | `/session/{email}/reset-history` | Clear one conversation's transcript, keep the account |
| DELETE | `/session/{email}/thread/{thread_id}` | Delete a conversation |
| GET/PUT/DELETE | `/session/{email}/preferences` | Read, replace, or clear saved shopping preferences |
| GET | `/session/{email}/orders` | Order history, for the receipts page |
| GET | `/session/{email}/logs` | Audit trail of every tool call this shopper's turns made |
| POST | `/cart/{email}` | Add a product (or bump quantity of an existing line) |
| PATCH | `/cart/{email}/size` | Move a cart line to a different size |
| DELETE | `/cart/{email}/{product_id}` | Remove a line (optionally scoped to one size) |
| POST | `/chat` | One full turn, blocking, returns the complete result |
| POST | `/chat/stream` | Same turn, streamed as SSE progress events + a final payload |
| GET | `/health` | Liveness + active session count |

## Communication flow

```
Browser (Shopper Agent / React)
        │  HTTP, JSON            (email + thread_id on every call)
        ▼
Personal Agent  ── OpenAI Chat Completions API  (tool-calling loop)
        │
        └── httpx → Seller Agent   (X-Buyer-Key on every call)
                     /message  /facets  /stock  /order  /payment/verify
                     (negotiates + verifies products; never trusts seller prose)
```

The shopper never talks to the Seller Agent, and this agent never talks to
Razorpay. Order creation and payment verification belong to the merchant.
