# Agentic Commerce Project — Build Plan (v2)
**Track:** Razorpay Buildathon — Track 1 (AI Growth & Agentic Commerce)
**Stack:** OpenAI API (raw SDK, function calling — no LangChain) + FastAPI (x2 servers) + React chat UI + Chroma (local vector DB) + Razorpay Test Mode

---

## Why no LangChain
Two agents, ~3 tools total, single-session chat. OpenAI's native function calling covers everything needed. Raw SDK = full visibility, easier debugging, easier to explain to judges. LangChain's abstractions (chains, agent executors, memory managers) solve problems this project doesn't have.

---

## Architecture Overview

```
[React Chat UI] ⇄ [Personal Agent :8000] ⇄ [Seller Agent :8001]
                         ↓                        ↓
                  Razorpay Test API      LLM + Tool-Calling Layer
                  (pay against order_id)   ├── search_catalog (RAG)
                                           ├── create_order (Razorpay)
                                           └── check_stock
```

**Key correction from v1:** Seller Agent is NOT a set of fixed REST endpoints (`/query`, `/create_order`) triggered by a known message format. Personal Agent sends **free-text natural language** — Seller Agent doesn't know in advance whether it's a search, a purchase confirmation, or a cancellation.

So Seller Agent = **one endpoint** (`/message`) backed by an **LLM with tool-calling**, which:
1. Reads the incoming free-text message
2. Decides which tool (if any) is needed
3. Extracts parameters itself (no fixed schema assumed from sender)
4. Calls the tool, reasons over the result, replies in natural language + structured data

Same pattern applies to Personal Agent — it also uses tool-calling (its tools: `message_seller`, `pay_order`, `ask_user`).

---

## Phase 0 — Setup & Environment
- [ ] Razorpay test account → Test Key ID + Secret
- [ ] OpenAI API key
- [ ] Folders: `personal-agent/`, `seller-agent/`, `frontend/`
- [ ] Install: `fastapi`, `uvicorn`, `openai`, `chromadb`, `razorpay`, `python-dotenv`
- [ ] `.env` files for both agents (keys never hardcoded)

**Validation:**
- [ ] Razorpay test key works via a raw "create order" call
- [ ] OpenAI key returns a basic completion
- [ ] OpenAI function-calling test: define a dummy tool, confirm model calls it correctly

**Fallback:**
- Razorpay sandbox down → mock order response locally (`order_id: "test_mock_123"`)

---

## Phase 1 — Seller Agent: Catalog + RAG (retrieval layer only)
**Goal:** Build the data source the LLM will query as a tool.

- [ ] Create 15–20 dummy products (JSON: id, name, description, price, stock, tags)
- [ ] Embed descriptions into Chroma (local, in-memory)
- [ ] Write a plain Python function `search_catalog(query, top_k=3)` — NOT an HTTP endpoint, just a callable function the LLM will invoke as a tool

**Validation:**
- [ ] Direct function test: `search_catalog("sweatproof earbuds under 1000")` → relevant results
- [ ] Empty/no-match query → returns `[]` cleanly, no crash

**Fallback:**
- Chroma fails to load/query → catch exception, return `[]` + log error (agent should treat this as "no results found", not crash)

---

## Phase 2 — Seller Agent: Tools Definition
**Goal:** Define all actions the Seller Agent's LLM can take.

Define 3 tools (OpenAI function-calling schema):

1. **`search_catalog(query: str)`** → wraps Phase 1 function, returns top-K matches
2. **`check_stock(product_id: str)`** → returns current stock boolean/count
3. **`create_order(product_id: str, buyer_name: str, buyer_address: str)`**
   - Re-validates price + stock at call time (avoid stale data)
   - Calls Razorpay Orders API (merchant keys)
   - Returns `order_id`, `amount`, `currency`

**Validation:**
- [ ] Each tool function tested standalone (before LLM ever calls them)
- [ ] `create_order` produces a real order_id visible in Razorpay test dashboard

**Fallback / Error Handling (inside each tool):**
- [ ] `create_order`: if stock is 0 by now → return `{"error": "out_of_stock"}` (LLM will relay this to Personal Agent)
- [ ] `create_order`: if Razorpay API fails → retry once → if still fails, return `{"error": "order_creation_failed"}`
- [ ] All tool calls logged (input, output, timestamp) → audit trail

---

## Phase 3 — Seller Agent: LLM + Tool-Calling Layer
**Goal:** The actual "brain" — decides which tool to use based on free-text input.

- [ ] Build single endpoint: `POST /message` — accepts `{"session_id": "<id>", "text": "<free text from Personal Agent>"}`
- [ ] System prompt instructs LLM: "You are a merchant assistant. You have tools to search products, check stock, and create orders. Decide which tool(s) to use based on the message. If information is missing to call a tool (e.g., no buyer address for an order), ask for it instead of guessing."
- [ ] Pass all 3 tools from Phase 2 into the OpenAI function-calling request
- [ ] LLM decides: call `search_catalog`? call `create_order`? or just reply directly (e.g., message was just "thanks")
- [ ] If a tool is called, feed result back to LLM → LLM composes final natural-language + structured reply
- [ ] Response includes **reasoning** (why this product/decision) — needed for "explainable" requirement

**Validation:**
- [ ] Send: "Do you have sweatproof earbuds under 1000?" → LLM correctly calls `search_catalog`, not `create_order`
- [ ] Send: "Please create the order for product P123, buyer Rahul, address XYZ" → LLM correctly calls `create_order`
- [ ] Send: "Never mind, cancel" → LLM replies without calling any tool
- [ ] Send an ambiguous message → LLM asks for clarification instead of guessing wrong tool

**Fallback / Error Handling:**
- [ ] LLM picks wrong tool / missing params → tool function itself validates params, returns clear error → LLM relays it back asking for the missing info (don't let it silently fail)
- [ ] OpenAI API call fails/times out → retry once → return graceful error message
- [ ] Tool returns error (e.g., `out_of_stock`) → LLM must relay this in plain language, not swallow it

---

## Phase 3.5 — Seller Agent: Conversation History / Session State
**Goal:** Seller Agent must remember prior turns in the same transaction — without it, references like "that one" or "the earbuds you showed me" can't be resolved.

**Why this is needed:** A real exchange spans multiple messages:
```
Personal Agent: "Do you have sweatproof earbuds under 1000?"
Seller Agent:   "Yes, Product P123, ₹899"
Personal Agent: "Great, create the order for that one, buyer: Rahul, address: XYZ"
```
Without memory, "that one" has no referent — Seller Agent would have to guess or hallucinate a `product_id`.

- [ ] Personal Agent generates one `session_id` per user conversation/transaction, reuses it for every message sent to Seller Agent
- [ ] Seller Agent maintains an in-memory session store: `{session_id: [list of {role, content} messages]}`
- [ ] On each `/message` call: append incoming message to that session's history, send **full history** (not just latest message) to the LLM
- [ ] Append LLM's reply (and any tool calls/results) back into the same session history

**Validation:**
- [ ] Two-turn test: "show me sweatproof earbuds under 1000" → then "buy that one, buyer Rahul, address XYZ" → confirms correct `product_id` resolved from context, `create_order` called with right product
- [ ] Confirm two different `session_id`s don't leak context into each other (session isolation test)

**Fallback / Error Handling:**
- [ ] Unknown or missing `session_id` → start a fresh empty session, don't crash
- [ ] Session history grows unbounded in a long-running demo → cap history length (e.g., last 20 messages) to avoid token bloat
- [ ] Server restart wipes in-memory sessions → acceptable for hackathon scope, but note as a known limitation (production would use Redis/DB-backed sessions)

---

## Phase 4 — Personal Agent: Tools + LLM Layer
**Goal:** Mirror architecture — Personal Agent also uses tool-calling, not fixed logic.

Define Personal Agent's tools:
1. **`message_seller(text: str)`** → sends free-text + the transaction's `session_id` to Seller Agent's `/message`, returns Seller's reply
2. **`ask_user(question: str)`** → surfaces a clarifying question back to human via chat UI
3. **`pay_order(order_id: str, amount: int)`** → calls Razorpay Payment API using test UPI (`success@razorpay`)

- [ ] Build `/chat` endpoint — accepts user message, maintains conversation state
- [ ] System prompt: "You are a shopping assistant. Understand the user's need, ask clarifying questions if needed, talk to the seller via `message_seller`, enforce the user's budget, and only call `pay_order` after explicit user confirmation."
- [ ] Enforce budget check **in code**, not just LLM judgment (hard guardrail — see Phase 6)

**Validation:**
- [ ] Vague input ("get me earbuds") → LLM calls `ask_user` for budget/preference before messaging seller
- [ ] Complete input → LLM calls `message_seller` directly
- [ ] After seller confirms product → LLM calls `ask_user` for final purchase confirmation before paying
- [ ] Only after explicit "yes" → LLM calls `pay_order`

**Fallback / Error Handling:**
- [ ] `message_seller` timeout/unreachable → tool returns error → LLM tells user "seller unavailable, try again shortly"
- [ ] Seller reports out-of-stock/no-match → LLM relays to user, offers to broaden search
- [ ] Max 2–3 clarification rounds → after that, LLM proceeds with best-guess assumption and states it explicitly

---

## Phase 5 — Payment Execution
**Goal:** Complete transaction once `pay_order` tool is triggered.

- [ ] `pay_order` calls Razorpay Payment API with test UPI (`success@razorpay` / `failure@razorpay` for testing)
- [ ] Verify payment status via Razorpay fetch API (don't rely solely on webhook for demo reliability)
- [ ] Guard against double-payment: mark order_id as "paid" after first successful call, block reuse

**Validation:**
- [ ] Full success path: order_id → pay_order → confirmed
- [ ] Full failure path: `failure@razorpay` → LLM reports failure clearly, offers retry (doesn't auto-retry silently)

**Fallback / Error Handling:**
- [ ] Payment API timeout → retry once → if still fails, log + tell user clearly
- [ ] Duplicate `pay_order` call on same order_id → blocked with explicit message, not silently re-charged

---

## Phase 6 — Guardrails & Bounded Behavior (Track requirement)
**Goal:** Make "explainable, bounded, gated" auditable — don't just rely on LLM judgment.

- [ ] Hardcode max auto-spend limit (e.g., ₹2000) as a **code-level check** inside `pay_order`, independent of LLM — LLM cannot bypass this even if it "decides" to
- [ ] Every tool call (both agents) logs: timestamp, tool name, input, output, and one-line reasoning
- [ ] `/logs` endpoint on both servers to display audit trail live during demo

**Validation:**
- [ ] Attempt purchase above spend limit → `pay_order` tool itself blocks it regardless of what LLM decided → user is asked to confirm override explicitly
- [ ] Pull logs after a full run → every decision point traceable end-to-end

---

## Phase 7 — Frontend (React Chat UI)
- [ ] Chat window: message list + input box, talks to Personal Agent `/chat`
- [ ] Renders clarifying questions, product suggestions, confirmation prompts, final receipt
- [ ] Optional "Agent Activity Log" side panel — pulls from `/logs`, shows tool calls live (strong demo visual)

**Validation:**
- [ ] Full conversation flow visually works start to finish
- [ ] Agent/tool errors shown gracefully in UI, no blank crashes

---

## Phase 8 — Final Testing & Demo Prep
- [ ] Test 3 full scenarios:
  1. Happy path — clear request → smooth purchase
  2. Clarification path — vague request → Qs → purchase
  3. Failure path — no match / over budget / payment failure — each triggers correct fallback
- [ ] Confirm logs show clear reasoning trail for all 3 scenarios
- [ ] Prepare pitch: problem → architecture (LLM + tools, not fixed endpoints) → live demo → guardrails → real-world mapping (NPCI UAP / AP2)

---

## Error Handling Philosophy (applies throughout)
| Failure type | Response |
|---|---|
| No product match | Tool returns empty → LLM relays clearly, asks to broaden |
| Budget exceeded | Blocked at code level in `pay_order`, not just LLM discretion |
| Seller/Personal agent unreachable | Timeout + friendly retry message via tool error |
| Payment fails | Reported clearly, retry offered — never silent |
| LLM/tool-calling API fails | Retry once, then graceful error |
| Ambiguous incoming message | LLM asks for clarification instead of guessing wrong tool |
| Missing tool parameters | Tool validates inputs, returns explicit error back to LLM |

---

## Suggested Folder Structure
```
project/
├── personal-agent/
│   ├── main.py              # /chat endpoint
│   ├── tools.py             # message_seller, ask_user, pay_order
│   ├── razorpay_client.py
│   ├── logs.json
│   └── .env
├── seller-agent/
│   ├── main.py              # /message endpoint
│   ├── tools.py             # search_catalog, check_stock, create_order
│   ├── catalog.json
│   ├── rag.py                # Chroma setup + search_catalog logic
│   ├── logs.json
│   └── .env
└── frontend/
    └── (React app)
```