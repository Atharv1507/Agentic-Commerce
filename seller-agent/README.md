# Seller Agent

The merchant-side agent. It owns the catalogue, its own pricing policy, its own
Razorpay account and its own books. It answers briefs from buyer agents — its
system prompt says so explicitly: "You are talking to another AI agent, not a
human."

It is no longer coupled to one specific buyer. Any AI buyer agent that can read
`/.well-known/agent.json` and hold a key can search, negotiate, buy and verify
payment here. What it *cannot* do is read the catalogue directly: every path
goes through this service's own search and ranking, so the merchant decides
what's relevant rather than handing over its inventory.

## Tech stack

- **FastAPI** + **uvicorn** — HTTP API, run with `python main.py` (port 8001
  by default, `SELLER_AGENT_PORT` to override)
- **OpenAI** (`gpt-5-mini` by default) — maps a brief onto `search_catalog`
  arguments (price band, colours, brands, size, exclusions)
- **ChromaDB** (`chromadb.Client()`, in-memory, no persistence) — vector store
  for the product catalogue, loaded once at startup from `catalog.json`
- **razorpay** SDK — order creation and payment verification. This service is
  the only party that touches Razorpay; buyer agents never hold merchant
  payment credentials
- Search ranking in `rag.py` blends semantic similarity, keyword overlap,
  budget fit, colour/material/brand match and a per-brand cap into one score
  — plain Python, not an LLM call
- `campaigns.py` is the revenue policy — a deterministic rules engine, not an
  LLM, because a discount must be identical for the same basket every time and
  must not be something a buyer can argue its way into
- `ledger.py` persists every order to `orders.json` (atomic tmp-write +
  `os.replace`, synchronous — a queued write lost at process exit is lost
  revenue), and `analytics.py` aggregates it for the merchant
- Negotiation sessions are in-memory (`dict`, capped at 200, evicted
  oldest-first) and **namespaced per authenticated buyer**, so two buyers using
  the same session id string cannot read or delete each other's context

## Auth

Two separate credentials, because they answer different questions:

| Header | Purpose |
|---|---|
| `X-Buyer-Key` | Identifies a buyer agent. Scopes its session namespace and attributes revenue to it. Configured as `BUYER_API_KEYS=key:buyer_id,...` |
| `X-Merchant-Key` | Reads the merchant's own books. A buyer key is refused — one buyer agent must not see another's revenue contribution |

**Both are optional for a local demo.** Left unset, the service falls back to
the public demo keys already committed in `.env.example` — which
`personal-agent` also defaults to — so a fresh clone runs end-to-end with no
setup step. Two buyer slots are defaulted, not one: `personal_agent` for the
bundled buyer, and `external_demo_agent` for a buyer agent nobody has met.
When that second key is live, the manifest publishes it as `auth.demo_key`, so
an unknown third-party agent can get from discovery to its first authenticated
call without anyone to contact. It is read back out of the configured key
table, so the manifest can never advertise a key that would 401. It warns on every boot and reports `using_demo_keys: true` on
`/health` while in that mode. Setting either variable replaces the demo value
outright, so the demo key stops working the moment you configure a real one.

The alternative (fail closed on unset) was worse in practice: the service
starts healthy, then 401s every search with no visible cause, which reads as a
broken build rather than a skipped config step. Since the demo keys are already
public in the repo, defaulting to them gives away nothing.

`/`, `/health` and `/.well-known/agent.json` are deliberately open: a buyer needs
to read how to get a key before it has one.

## Flow

1. A buyer agent GETs `/.well-known/agent.json` to learn what this merchant
   sells, what it can do, and how to authenticate. An agent that was handed
   only the base URL and does not know the well-known convention gets the
   same manifest from `GET /`, inlined — a 404 at the root reads as a dead
   host rather than a wrong path.
2. It posts a brief to `/message` — either a structured `brief` (schema
   published in the manifest) or free-form `text`, or both. A structured brief
   is rendered server-side into this shop's canonical instruction and then runs
   through **the same** tool-calling loop as prose. The schema is a stable
   contract for the caller, not a fast path around the merchant's reasoning.
3. An OpenAI tool-calling loop (`MAX_TOOL_ITERATIONS = 5`) decides which
   tool(s) to call — usually `search_catalog`, sometimes `price_range` when the
   ask is far off stock, and `evaluate_offers` when a campaign might be worth
   surfacing.
4. **Read-only rounds short-circuit**: once a round's tool calls are all drawn
   from `search_catalog` / `price_range` / `check_stock` / `evaluate_offers`,
   the loop stops rather than paying for a completion to write prose the caller
   discards anyway (it reads `tool_results`). `create_order` is excluded and
   still gets full multi-round reasoning, since it's a real mutation.
5. Tool calls within a round run concurrently (`ThreadPoolExecutor`) — they're
   independent, I/O-bound catalogue lookups.
6. `/facets`, `/stock`, `/order` and `/payment/verify` are deliberately **not**
   LLM calls. They need to be exact, fast and always correct; a model that
   paraphrases "0 in L" as "in stock" would let the shop take money for a
   garment it cannot send.
6b. Colour and fabric are **ranking signals, not filters** — a search for
   green legitimately returns black when little green ranks well. Each product
   therefore carries `matches_color` / `color_match` (`exact` / `adjacent` /
   `none`) and `matches_material`, and the result carries a `constraint_fit`
   summary counting how many actually match. `applied_constraints` on its own
   reads as a promise the results keep, and for these two it is not one: a
   buyer agent with no eyes on the images cannot tell "Olive Green" from "Jet
   Black" by parsing free text, and buying the wrong colour is the expensive
   mistake.
7. `/order` prices the basket via `campaigns.price_basket`, creates the
   Razorpay order, and writes it to the ledger against the calling buyer's id.
8. `/order` also returns a **`payment_url`** — a Razorpay payment link bound to
   that order's amount. Without it the `purchase` capability stopped one step
   short of a payment any third party could complete: a Razorpay `order_id` can
   only be paid by the *browser* Checkout SDK, which needs a DOM and a human at
   a card form. A headless buyer agent has neither, so it could negotiate,
   price and create an order and then be stranded. The link closes that, and
   the merchant's `key_secret` still never leaves this service. The order also
   returns `razorpay_key_id`, the merchant's *publishable* key, so the browser
   Checkout rail the `payment_note` describes is actually usable — it named a
   `key_id` it never supplied.
9. A payment link collects through an order **Razorpay creates itself**, so the
   payment never attaches to the order in the ledger — `order.fetch` on our id
   reports "created" forever no matter how completely the link was paid.
   `verify_payment` therefore falls back to looking the link up by
   `reference_id` (our order id) and always reports the id *this* ledger knows,
   never Razorpay's internal one. Settling against the wrong id would mark an
   unknown order paid and leave the real one showing unpaid revenue.
10. **The shop finds out it was paid without the buyer's help** (`settlement.py`).
    A buyer agent typically hands the `payment_url` to its user and finishes;
    the user pays minutes or hours later in a browser that agent never sees. If
    settlement depended on the buyer calling `/payment/verify`, that sale would
    be captured by Razorpay and reported unpaid by this shop indefinitely, and
    no wording in the manifest could fix it — the process that read the
    instruction is gone. So there are two paths that don't involve the buyer:
    a **Razorpay webhook** (`POST /razorpay/webhook`, HMAC-authenticated), which
    settles promptly with nobody watching, and **reconciliation on read**, which
    re-verifies unpaid orders before the merchant's analytics are totalled and
    needs no public URL. Both refuse to write to an order id this ledger does
    not already contain, for the reason in step 9.

## Settlement

`POST /razorpay/webhook` is how a payment link settles on its own. Configure it
once, in the Razorpay dashboard under **Settings -> Webhooks**:

| | |
|---|---|
| URL | `<your_public_url>/razorpay/webhook` |
| Events | `payment_link.paid`, `order.paid`, `payment.captured` |
| Secret | any string; put the same value in `RAZORPAY_WEBHOOK_SECRET` |

The signature is the route's only credential — it is not behind a buyer or
merchant key, because Razorpay holds neither. So an unset `RAZORPAY_WEBHOOK_SECRET`
makes the route reject every delivery rather than fall back to a demo value the
way the API keys do: an endpoint that books revenue must not accept
unauthenticated callers. The service warns on boot while the secret is missing.

A delivery about an order this shop doesn't own answers `200` with
`handled: false`. That is not an error — the Razorpay account may have other
integrations — and a non-2xx would only earn a retry of something that can
never succeed. Only a failed signature is a `4xx`.

Reconciliation is the backstop, and covers what a webhook cannot: a deployment
with no public URL, a webhook added after orders were already paid, and dropped
deliveries. `GET /merchant/analytics` runs it before aggregating and reports what
it did under `reconciled`. It is read-only against Razorpay, skips orders whose
payment link has expired, and rate-limits itself, so a dashboard open costs at
most a couple of API calls.

## Campaigns

Four kinds, in `campaigns.py`: a spend **threshold discount**, a shirt +
T-shirt **bundle**, a **cross-sell** suggestion (no price change), and
**lifecycle** first-order / win-back offers.

Two invariants worth knowing:

- **Discounts never stack.** Only the single best-value campaign is applied.
- **Every discount is capped** at `MAX_DISCOUNT_RATIO` of the subtotal, so a
  mis-specified rule costs a rounding error rather than the order.

Lifecycle offers depend on `buyer_context` (order count, days since last
order), which the buyer's agent self-reports and this service cannot verify.
That's why it may only ever *unlock a discount*: a buyer lying there can cost
the merchant margin, never overcharge a shopper.

## Endpoints

| Method | Path | Auth | Purpose |
|---|---|---|---|
| GET | `/` | none | Pointer for a caller that only has the base URL, with the manifest inlined |
| GET | `/.well-known/agent.json` | none | Self-describing manifest: capabilities first, then callable schemas |
| POST | `/message` | buyer | Run one brief (structured, prose, or both) through the tool-calling loop |
| DELETE | `/session/{session_id}` | buyer | Drop one negotiation's context (only ever the caller's own) |
| POST | `/facets` | buyer | Non-LLM: colours/brands/fabrics/price bands that actually exist |
| POST | `/stock` | buyer | Non-LLM: exact per-size stock for a list of product IDs |
| POST | `/order` | buyer | Non-LLM: price, validate stock, create the Razorpay order + `payment_url`, record it |
| POST | `/payment/verify` | buyer | Non-LLM: confirm payment on either rail (browser checkout or payment link), settle the ledger |
| POST | `/razorpay/webhook` | **HMAC signature** | Razorpay reports a capture; settles the ledger with no buyer agent in the loop |
| GET | `/merchant/analytics` | **merchant** | Revenue, AOV, revenue per buyer agent, attach rate, campaign impact |
| GET | `/health` | none | Liveness, active session count, and whether demo keys are in use |

### Refusals

`/order` and `/payment/verify` answer a refusal with a status code that means
it, not a 200 with an `error` key — a caller that checks the status, which is
the normal thing to do, used to read "not available in M" as a sale.

| `error` | Status | Why |
|---|---|---|
| `product_not_found` | 404 | The id does not exist. Search again; do not retry it |
| `invalid_size` / `no_valid_products` | 422 | The request itself is malformed |
| `size_unavailable` / `out_of_stock` | 409 | Request is fine, live stock conflicts — pick another size |
| `order_creation_failed` / `verification_failed` | 502 | Razorpay failed or was unreachable; retry is reasonable |

The body is unchanged and every refusal carries a `message` saying what to do
next, so callers that already read `error` keep working. An unclassified
refusal keeps 200 rather than being guessed at with a misleading code. On the
buyer's side `create_seller_order` passes a structured 4xx body straight
through instead of collapsing it into `seller_unreachable` — the shopper needs
"not available in L, try M", not "the shop is down".

`search_catalog`, `price_range`, `check_stock`, `evaluate_offers` and
`create_order` are also OpenAI function-calling tools (`schemas.py`), executed
in-process by `handlers.py`, for the model's use during `/message`.

## Communication flow

```
Any AI buyer agent
        │  HTTP, JSON  (X-Buyer-Key on every call)
        ▼
Seller Agent  ── OpenAI Chat Completions API  (tool-calling loop)
        │
        ├── ChromaDB (in-memory, loaded from catalog.json)
        ├── campaigns.py  (deterministic pricing policy)
        ├── ledger.py → orders.json  (durable, per-buyer attribution)
        └── razorpay SDK → Razorpay API  (order.create, payment_link.create,
                                          payment.fetch, payment_link.all)

Merchant's dashboard ──(X-Merchant-Key)──▶ GET /merchant/analytics
```

CORS is enabled for exactly one caller — the merchant analytics dashboard,
which is a browser. All buyer traffic is server-to-server and needs none.

## Known limitations

- **Same product, two sizes, one order**: `create_order`'s `sizes` map is keyed
  by product id, so one shirt ordered in both M and L can't be expressed.
- **Per-unit stock re-check on quantity > 1**: repeating a product id N times
  checks the same static count N times rather than as an aggregate. The real
  protection is the buyer's `/stock` pre-check before `/order`.
- `buyer_context` is self-reported and unverified (see Campaigns above).
- Static keys, no rotation, no rate limiting — a hackathon build.
