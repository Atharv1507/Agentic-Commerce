# Drape AI — Agentic Commerce on Razorpay

## The problem

Online shopping is built for humans clicking through web pages. When an AI agent
shops for someone, it hits a storefront that was never built for it. It has no
clean way to find out what the shop sells, no way to negotiate, and no way to pay
without a browser and a human at a card form.

This project makes a **merchant AI-transactable**. The shop runs its own AI agent
that any buyer agent can discover, brief, negotiate with, buy from and pay,
end to end over HTTP. The merchant keeps control of its catalogue, pricing,
discounts, Razorpay account and books.

## Architecture

```
Shopper (browser)
   │
   ▼
Shopper Agent  (React client, :5173)
   │  JSON / SSE
   ▼
Personal Agent (buyer's agent, :8000) ──── OpenAI (tool-calling loop)
   │  X-Buyer-Key
   ▼
Seller Agent   (merchant's agent, :8001) ── OpenAI · Razorpay
   ▲
   │  any third-party AI buyer agent can use the same API
   │  (discovered via /.well-known/agent.json)
```

| Component | Folder | Role |
|---|---|---|
| **Shopper Agent** (client) | `Shopper Agent/` | Chat UI the shopper sees: product cards, cart, Razorpay checkout, receipts, merchant dashboard |
| **Personal Agent** | `personal-agent/` | Buyer-side agent. Owns the conversation, profile, cart, preferences and spend limit, and negotiates with the seller on the shopper's behalf |
| **Seller Agent** | `seller-agent/` | Merchant-side agent. Owns the catalogue, search/ranking, campaigns, Razorpay orders and payments, the ledger and analytics |

Money stays with the merchant. The Personal Agent holds **no Razorpay
credentials**. The Seller Agent creates orders and verifies payments.

## Tech stack

### Shopper Agent (client)
- **React 19** + **Vite 8** (static SPA, no backend of its own)
- **Tailwind CSS v4** + **shadcn / Radix UI** components, **lucide-react** icons
- **framer-motion** (transitions), **@paper-design/shaders-react** (animated background)
- **react-markdown** + **remark-gfm** (agent replies)
- **Razorpay Checkout.js** (payment modal)
- Server-Sent Events for live agent progress

### Personal Agent
- **Python**, **FastAPI** + **uvicorn**
- **OpenAI** function calling (`gpt-5-mini` by default)
- **httpx** to talk to the Seller Agent
- Flat-file persistence (`sessions.json`, atomic background writes)

### Seller Agent
- **Python**, **FastAPI** + **uvicorn**
- **OpenAI** function calling (`gpt-5-mini` by default)
- **OpenAI embeddings** (cached, numpy cosine search over a 300-product `catalog.json`) + a custom hybrid ranker
- **Razorpay Python SDK**: orders, payment links, payment verification, webhooks
- Deterministic rules engine for campaigns (no LLM in pricing)
- `orders.json` ledger, rebuildable from Razorpay order `notes`

## Functions at a glance

### Personal Agent: LLM tools (`personal-agent/handlers.py`)
| Tool | What it does |
|---|---|
| `find_products` | Briefs the Seller Agent, checks every result against the shopper's constraints itself, and re-negotiates up to 3 rounds |
| `ask_preferences` / `ask_user` | Ask the shopper a question or show a chip picker |
| `list_options` | Fetch real colours, brands, fabrics and price bands from the seller |
| `check_availability` | Exact per-size stock |
| `add_to_cart` / `update_cart` | Cart management with sizes and quantities |
| `checkout_cart` | Validates cart, details and stock, enforces the spend limit, then asks the merchant to create the order |
| `verify_payment` | Asks the merchant to confirm payment (idempotent) |
| `update_profile` / `save_preferences` / `clear_preferences` | Shopper profile and saved preferences |

### Seller Agent: LLM tools (`seller-agent/handlers.py`)
| Tool | What it does |
|---|---|
| `search_catalog` | Hybrid semantic + keyword + budget/colour/brand ranking over the catalogue |
| `price_range` | What the shop actually stocks around a price |
| `check_stock` | Per-size stock lookup |
| `evaluate_offers` | Surfaces any live campaign for a basket |
| `create_order` | Prices the basket, creates the Razorpay order and payment link, writes the ledger |

### Key endpoints
| Service | Endpoints |
|---|---|
| Personal Agent | `/onboarding`, `/chat`, `/chat/stream`, `/cart/{email}`, `/session/{email}` (+ `/orders`, `/preferences`, `/logs`), `/health` |
| Seller Agent (buyer) | `/.well-known/agent.json`, `/message`, `/facets`, `/stock`, `/order`, `/payment/verify` |
| Seller Agent (merchant / Razorpay) | `/merchant/analytics`, `/merchant/rehydrate`, `/razorpay/webhook` |

Full endpoint tables are in each component's own README.

## Major workflows

1. **Onboarding and sessions.** The shopper signs up or skips. The Personal
   Agent keeps a profile, preferences, cart and multiple chat threads per email.

2. **Agent discovery.** Any buyer agent reads `GET /.well-known/agent.json` (or
   `GET /`) to learn what the shop sells, what it can do, how to authenticate,
   and the request schemas.

3. **Agent-to-agent negotiation.** The shopper's request becomes a structured
   brief (budget band, colour, size, fabric). The Seller Agent searches and
   ranks. The Personal Agent checks each product against the brief and, if too
   few match, tightens the brief and asks again (up to 3 rounds). Progress
   streams live to the UI.

4. **Cross-sell.** After the main item, a second negotiation pass finds a
   complementary product (for example, a T-shirt with a shirt).

5. **Merchant campaigns.** Threshold discounts, shirt + T-shirt bundles,
   cross-sell suggestions, and first-order / win-back offers. Discounts never
   stack, are capped, and are shown to the shopper in the merchant's own words.

6. **Cart and stock.** The shopper or the agent can add, remove and resize cart
   items. Stock is checked per size before checkout.

7. **Checkout with guardrails.** Code, not the prompt, enforces the spend limit.
   The shopper can't talk the agent into raising it. An over-limit override
   needs an exact phrase match, and the limit is checked again against the
   merchant's final price.

8. **Payment on two rails.** In the browser, Razorpay Checkout.js pays the
   order. For headless agents, the order also returns a Razorpay **payment
   link**, so an agent without a browser can still complete the purchase.

9. **Settlement without the buyer.** A Razorpay webhook (HMAC-verified) and
   reconciliation when analytics load both mark orders paid, even if the buyer
   agent never calls `/payment/verify`.

10. **Ledger durability.** Each order's details are stored in Razorpay `notes`.
    If `orders.json` is lost (for example, after a redeploy), the ledger is
    rebuilt from Razorpay automatically.

11. **Receipts and tracking.** The client shows an order history, a
    downloadable receipt and an order-tracking timeline.

12. **Merchant analytics.** A dashboard (behind `X-Merchant-Key`) shows revenue,
    AOV, revenue per buyer agent, cross-sell attach rate, campaign impact and
    top products.

13. **Audit trail.** The Personal Agent logs every tool call per shopper and
    shows it in the client's activity panel.

## Setup guide

### Prerequisites
- Python 3.10+
- Node.js 20.19+ (required by Vite 8)
- An OpenAI API key
- A Razorpay account. Test-mode keys are fine: Dashboard → Account & Settings → API Keys

### 1. Seller Agent (port 8001)
```bash
cd seller-agent
python3 -m venv venv && source venv/bin/activate
pip install -r requirements.txt
cp .env.example .env
```
In `.env`, set:
- `OPENAI_API_KEY`
- `RAZORPAY_KEY_ID`
- `RAZORPAY_KEY_SECRET`

Then start it:
```bash
python main.py
```

### 2. Personal Agent (port 8000)
Open a new terminal:
```bash
cd personal-agent
python3 -m venv venv && source venv/bin/activate
pip install -r requirements.txt
cp .env.example .env
```
In `.env`, set `OPENAI_API_KEY`. Then start it:
```bash
python main.py
```

### 3. Shopper Agent client (port 5173)
Open a new terminal:
```bash
cd "Shopper Agent"
npm install
cp .env.example .env
```
In `.env`, set `VITE_RAZORPAY_KEY_ID` to the same key ID the Seller Agent uses. Then start it:
```bash
npm run dev
```
Open http://localhost:5173.

### 4. Check that everything is running
- `curl http://localhost:8001/health`
- `curl http://localhost:8000/health`

### Notes
- **Demo keys:** the buyer and merchant API keys (`BUYER_API_KEYS`,
  `SELLER_BUYER_KEY`, `MERCHANT_API_KEY`, `VITE_MERCHANT_KEY`) fall back to
  public demo values. Local runs need no extra setup for them. Replace them
  before any real deployment.
- **Webhook (optional):** to have payment links marked paid automatically,
  expose the Seller Agent on a public URL. Then add a Razorpay webhook:
  - URL: `<public_url>/razorpay/webhook`
  - Events: `payment_link.paid`, `order.paid`, `payment.captured`
  - Secret: any value; set the same value as `RAZORPAY_WEBHOOK_SECRET`

  Without the webhook, orders are still reconciled whenever the merchant
  dashboard loads.
- **Testing a third-party agent:** point it at `http://localhost:8001/`. It
  can read the manifest and use the published demo key
  (`demo-external-agent-key`).
