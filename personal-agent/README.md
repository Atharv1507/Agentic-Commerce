# Personal Agent

The shopper-facing agent. It's the only backend service the frontend ever
talks to — everything else (catalogue search, payments, the seller's own
reasoning) happens behind it. It owns the conversation, the shopper's
profile/cart/preferences, and the decision of when and how hard to push the
Seller Agent for better results.

## Tech stack

- **FastAPI** + **uvicorn** — HTTP API, run with `python main.py` (port 8000
  by default, `PERSONAL_AGENT_PORT` to override)
- **OpenAI** (`gpt-5-mini` by default, `OPENAI_MODEL` to override) — function
  calling drives every decision: which tool to call, what to say
- **httpx** — synchronous client used to talk to the Seller Agent
- **razorpay** SDK — order creation and payment verification
- Persistence is a single flat file, `sessions.json` (one entry per shopper
  email; no database). Written atomically (temp file + `os.replace`) with the
  actual disk write and fsync done on a background thread so a chat reply
  never blocks on it.

## Flow

1. Frontend posts to `/onboarding` (or skips it) and then `/chat` /
   `/chat/stream` for every message, always with `email` + `thread_id`.
2. `run_chat_turn` (`main.py`) loads that shopper's session and the specific
   conversation thread, then runs an OpenAI tool-calling loop
   (`MAX_TOOL_ITERATIONS = 6`): call the model → if it wants a tool, execute
   it → feed the result back → repeat until the model returns plain text.
3. Tools live in `handlers.py` and are plain Python functions, never HTTP
   endpoints of their own (see `AGENTS.md`). The one that matters most is
   `find_products`, which hands off to `negotiation.py`.
4. `negotiation.py` is where the real "agentic commerce" happens: it turns
   the shopper's stated constraints (budget, colour, size, fabric...) into a
   numeric band, briefs the Seller Agent over HTTP, and **verifies every
   returned product against the constraints itself** — the seller's prose
   is never trusted. If too few products survive, it tightens the brief and
   asks again, up to `MAX_SELLER_ROUNDS = 3` (`2` for a cross-sell pass).
5. Checkout talks to Razorpay directly from this service (`handlers.py`) —
   the Seller Agent is never involved in payments, only in finding products.
6. The model's final reply, plus any structured `products`/`cart`/`profile`
   payload, goes back to the frontend as one JSON object (`/chat`) or as a
   stream of progress events ending in a `final` event (`/chat/stream`).

## Endpoints

All of these are **public** in the sense that the React frontend calls them
directly — there's no auth, this is a hackathon build (see the CORS comment
in `main.py`). There is no "private" tier on this service; anything not
listed here is a plain internal function, not a route.

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
| POST | `/chat/stream` | Same turn, but streamed as SSE progress events + a final payload |
| GET | `/health` | Liveness + active session count |

## Communication flow

```
Browser (Shopper Agent / React)
        │  HTTP, JSON            (email + thread_id on every call)
        ▼
Personal Agent  ── OpenAI Chat Completions API  (tool-calling loop)
        │
        ├── httpx → Seller Agent  /message  /facets  /stock
        │            (negotiates + verifies products; never trusts seller prose)
        │
        └── razorpay SDK → Razorpay API  (order.create, payment.fetch)
```

The shopper never talks to the Seller Agent, and the Seller Agent never talks
to Razorpay or the browser — this service is the sole hub between all three.
