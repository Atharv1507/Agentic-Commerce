# Seller Agent

The merchant-side agent. It owns the catalogue and answers briefs from the
Personal Agent — it has no concept of a shopper, a cart, or a payment, and it
is never called by the browser directly. Its system prompt says this
explicitly: "You are talking to another AI agent, not a human."

## Tech stack

- **FastAPI** + **uvicorn** — HTTP API, run with `python main.py` (port 8001
  by default, `SELLER_AGENT_PORT` to override)
- **OpenAI** (`gpt-5-mini` by default) — maps a natural-language brief onto
  `search_catalog` arguments (price band, colours, brands, size, exclusions)
- **ChromaDB** (`chromadb.Client()`, in-memory, no persistence) — vector store
  for the product catalogue, loaded once at startup from `catalog.json`
- Search ranking in `rag.py` blends semantic similarity, keyword overlap,
  budget fit, colour/material/brand match and a per-brand cap into one score
  — this is plain Python, not an LLM call
- Sessions are in-memory only (`dict[str, list]`, capped at 200, evicted
  oldest-first) — one per negotiation, not per buyer (see `main.py` comment)

## Flow

1. The Personal Agent posts a brief to `/message` with a `session_id` scoped
   to one search (not one buyer — a fresh id per `find_products` call, so a
   failed trousers search never leaks context into a shirts search).
2. An OpenAI tool-calling loop (`MAX_TOOL_ITERATIONS = 5`) decides which
   tool(s) to call — almost always `search_catalog`, sometimes `price_range`
   when the ask is far off what's in stock.
3. **Read-only rounds short-circuit**: once a round's tool calls are all
   drawn from `search_catalog` / `price_range` / `check_stock`, the loop
   stops right there instead of paying for another completion to compose a
   natural-language summary — the caller only ever reads `tool_results`
   (see `negotiation.py`'s `_products_from_reply`), so that prose was pure
   latency. `create_order` is excluded from the shortcut and still gets full
   multi-round reasoning, since it's a real mutation.
4. Tool calls within a round run concurrently (`ThreadPoolExecutor`) — they're
   independent, I/O-bound catalogue lookups, not sequential steps.
5. `/facets` and `/stock` are deliberately **not** LLM calls at all — they're
   asked for exact, fast, always-correct answers (what the Personal Agent
   shows in a clarifying form, and what it double-checks stock against right
   before charging someone), so they go straight to `rag.py`.

## Endpoints

All of these are **internal-only** — nothing but the Personal Agent is meant
to call this service. There's no separate "public" tier; every route here is
reachable over plain HTTP with no auth, same hackathon caveat as the Personal
Agent.

| Method | Path | Purpose |
|---|---|---|
| POST | `/message` | Run one brief through the tool-calling loop (search, mainly) |
| DELETE | `/session/{session_id}` | Drop one negotiation's scratch history |
| POST | `/facets` | Non-LLM: colours/brands/fabrics/price bands that actually exist for a query |
| POST | `/stock` | Non-LLM: exact per-size stock for a list of product IDs |
| GET | `/health` | Liveness + active session count |

`search_catalog`, `price_range`, `check_stock` and `create_order` are **not**
routes — they're OpenAI function-calling tools defined in `schemas.py` and
executed in-process by `handlers.py`. `create_order` in particular is wired
up as a tool but has no current caller: checkout is handled entirely by the
Personal Agent talking to Razorpay directly, so this path only matters if
something starts sending the Seller Agent a genuine purchase brief.

## Communication flow

```
Personal Agent  ── HTTP, JSON ──▶  Seller Agent
                                        │
                                        ├── OpenAI Chat Completions API (tool-calling)
                                        └── ChromaDB (in-memory, loaded from catalog.json)
```

No outbound calls to Razorpay, no calls to the browser, no calls back to the
Personal Agent — this service only ever answers what it's asked.
