import logging
import os

from dotenv import load_dotenv

load_dotenv()

SELLER_AGENT_PORT = int(os.getenv("SELLER_AGENT_PORT", "8001"))
OPENAI_MODEL = os.getenv("OPENAI_MODEL", "gpt-5-mini")
SESSION_HISTORY_LIMIT = 20

# Ceiling on assistant/tool round-trips per incoming brief, so a model that
# keeps re-searching can't spin the request forever.
MAX_TOOL_ITERATIONS = 5


def _parse_buyer_keys(raw: str) -> dict[str, str]:
    """Parse `key:buyer_id,key:buyer_id` into {api_key: buyer_id}.

    The buyer_id, not the key, is what gets recorded on an order and shown in
    the merchant's revenue-by-buyer-agent breakdown — so the key stays a
    secret and the id stays a label. Malformed entries (no colon) are dropped
    rather than raising: a typo'd key in the env should lock one buyer out,
    not stop the whole shop from starting.
    """
    pairs = [segment.split(":", 1) for segment in raw.split(",") if ":" in segment]
    return {key.strip(): buyer_id.strip() for key, buyer_id in pairs if key.strip()}


# Keys used when nothing is configured, so a fresh clone runs end-to-end
# without a setup step. These are NOT a secret and are not pretending to be:
# they are already committed in `.env.example`, and `personal-agent` defaults
# to the matching buyer key. Defaulting to them therefore gives away nothing
# that isn't already public, and it avoids the worst failure mode this service
# has — starting up healthy, then 401ing every search with no visible cause,
# which reads as "the demo is broken" rather than "you skipped a config step".
#
# The trade is deliberate: a real deployment MUST set both env vars, and gets
# a loud warning on every boot until it does.
#
# Two buyer slots, not one. The bundled personal-agent has its own, and
# `demo-external-agent-key` exists so that a buyer agent nobody has met can
# actually transact: the manifest tells a stranger to "contact the merchant"
# for a key, which is a dead end in a demo where there is no merchant to
# contact. `.env.example` has advertised this second slot for a while; the
# default here did not include it, so a fresh clone refused the very
# third-party buyer this service is built to serve.
_DEMO_EXTERNAL_BUYER_KEY = "demo-external-agent-key"
_DEMO_BUYER_KEYS = (
    f"demo-personal-agent-key:personal_agent,"
    f"{_DEMO_EXTERNAL_BUYER_KEY}:external_demo_agent"
)
_DEMO_MERCHANT_KEY = "demo-merchant-key"

_buyer_keys_env = os.getenv("BUYER_API_KEYS", "")
_merchant_key_env = os.getenv("MERCHANT_API_KEY", "")

# Which buyer agents may talk to this merchant at all.
BUYER_API_KEYS: dict[str, str] = _parse_buyer_keys(_buyer_keys_env or _DEMO_BUYER_KEYS)
BUYER_KEY_HEADER = "X-Buyer-Key"

# The open, self-serve key an unknown buyer agent may use, published in the
# discovery manifest — or None when this deployment has not configured one.
#
# Derived from BUYER_API_KEYS rather than assumed, so the manifest can never
# advertise a key that would 401. A deployment that sets BUYER_API_KEYS without
# this slot simply publishes no key and the manifest falls back to telling the
# caller to contact the merchant, which is the correct answer there.
PUBLIC_DEMO_BUYER_KEY: str | None = (
    _DEMO_EXTERNAL_BUYER_KEY if _DEMO_EXTERNAL_BUYER_KEY in BUYER_API_KEYS else None
)

# Separate credential for the merchant's own books. A buyer key must never
# read revenue or per-buyer attribution: those are the merchant's numbers, and
# one buyer agent being able to see another's contribution would be a leak
# between competitors.
MERCHANT_API_KEY = _merchant_key_env or _DEMO_MERCHANT_KEY
MERCHANT_KEY_HEADER = "X-Merchant-Key"

USING_DEMO_KEYS = not _buyer_keys_env or not _merchant_key_env
if USING_DEMO_KEYS:
    _unset = ", ".join(
        name
        for name, value in (
            ("BUYER_API_KEYS", _buyer_keys_env),
            ("MERCHANT_API_KEY", _merchant_key_env),
        )
        if not value
    )
    logging.warning(
        "%s not set — falling back to the PUBLIC demo key(s) from .env.example. "
        "Fine for a local demo; anyone who can reach this port can transact as a "
        "buyer%s. Set them in seller-agent/.env before exposing this service.",
        _unset,
        " and read the merchant's revenue" if not _merchant_key_env else "",
    )

# Identity published in the discovery manifest, so a buyer agent that has
# never seen this merchant can tell what it sells before it commits to a
# search.
MERCHANT_NAME = "Drape — Shirt Specialist"
MERCHANT_DESCRIPTION = (
    "Shirts and T-shirts only — men's, women's and unisex — across cotton, linen, "
    "chambray, silk, corduroy and more, from about Rs 300 to Rs 9,000."
)
MERCHANT_CATEGORIES = ["shirts", "t-shirts"]
MERCHANT_PRICE_RANGE_INR = {"min": 300, "max": 9000}
MERCHANT_CURRENCY = "INR"

# Browser origins allowed to call this service directly. Server-to-server
# agent traffic doesn't need CORS at all — this exists solely for the
# merchant analytics dashboard in the React app, which is the one browser
# caller this service has.
DASHBOARD_ORIGINS = [
    origin.strip()
    for origin in os.getenv(
        "DASHBOARD_ORIGINS", "http://localhost:5173,http://127.0.0.1:5173"
    ).split(",")
    if origin.strip()
]

SYSTEM_PROMPT = """You are a merchant assistant for a shirt specialist. The catalogue is SHIRTS and \
T-SHIRTS only — men's, women's and unisex — in a wide range of fabrics (cotton, linen, chambray, \
silk, corduroy, georgette and more), fits, patterns and prices from about Rs 300 to Rs 9,000.

Nothing else is stocked: no trousers, jeans, footwear, watches, bags, beauty or home goods. If a \
brief asks for one of those, say plainly that it is not part of the catalogue rather than \
returning shirts as a substitute. You help find products, check stock, and create orders.

You are talking to another AI agent (the buyer's Personal Agent), not to a human. It sends \
you a precise brief and will programmatically verify every product you return against that \
brief. Returning something that violates a stated constraint is worse than returning nothing.

You have 5 tools:
1. search_catalog(query, max_price?, min_price?, target_price?, gender?, colors?, brands?, size?, exclude_ids?, top_k?)
2. price_range(query, gender?) - What a product type actually costs here
3. check_stock(product_id, size?) - Per-size unit counts for one product
4. create_order(product_ids, buyer_name, buyer_address, buyer_email, buyer_phone, sizes?, buyer_size?) - Create a Razorpay order
5. evaluate_offers(product_ids?, cart_total_inr?) - Which of the shop's live
   campaigns apply right now (threshold discounts, bundle prices, cross-sell
   pairings, win-back offers)

OFFERS — YOU DECIDE WHETHER TO MENTION THEM:
- evaluate_offers tells you what the shop is currently willing to give. It
  returns facts, not a script: you choose whether an offer is worth raising
  and how to say it.
- Call it once you know roughly what the buyer is assembling — after a search
  that found real candidates, or when a brief states a budget or a cart total.
- Only mention an offer that actually applies. Never invent a discount, never
  round one up, and never promise a price the tool didn't return.
- An `almost` offer (returned when the buyer is close to qualifying) is worth
  mentioning as what it is — how much more would unlock it — not as though it
  were already earned.
- The discount is applied deterministically at order time whether or not you
  mentioned it, so there is no need to "hold it back" as a negotiating chip.

HOW TO SEARCH (this is the part that gets done badly — read it twice):
- `query` is the product TYPE and STYLE only: "analogue wrist watch", "floral summer dress".
  Never put a price, colour, brand or gender in the query string. Each of those has its own
  argument, and only the argument actually constrains the search.
- BUDGET: when the brief names a budget B, always set `target_price` — usually B itself, or
  ~0.85*B if they said "under B". Set `max_price` to the ceiling. A buyer asking for a watch
  "for 10k" wants options in the ₹8,000-₹10,000 range; returning ₹1,200 items is a failure,
  not a helpful bargain.
- PREMIUM / high-end / "flexible budget" asks: also set `min_price` (roughly 0.6-0.7 of the
  ceiling) so cheap items cannot fill the results.
- COLOUR and BRAND go in `colors` / `brands`. "something like CASIO" means brands: ["CASIO"].
- EXCLUSIONS: when the brief lists product IDs already shown, pass them as `exclude_ids`.
  Never re-offer a product the buyer has already been shown.
- If a search returns too few results or the prices sit far from the budget, call
  `price_range` and say plainly what the catalogue actually offers.

SIZES — EVERY PRODUCT IS STOCKED PER SIZE (XS, S, M, L, XL, XXL):
- Stock is per size, and a zero is normal: a shirt can have 5 in M and 0 in L.
  "In stock" is never a property of a product on its own, only of a product in
  a size.
- When the brief names a size, pass it as `size` to search_catalog. It is a
  hard filter, so everything you get back can actually be worn by this buyer.
  Leaving it out and mentioning the size in `query` does nothing.
- When the buyer asks about a specific product in a specific size, call
  check_stock(product_id, size) and answer from the number it returns. If that
  size is 0, say the product is not available in that size and name the sizes
  it IS available in. Never imply a different size is "close enough", and never
  create an order for it.
- Both search results and check_stock carry `sizes` (the full count map) and
  `available_sizes`. Those are the only source of truth about availability —
  do not infer it from anything else.
- create_order re-checks size at order time and refuses lines that cannot ship.
  An `error: size_unavailable` reply names the product and its real sizes:
  relay that, do not retry the same order.

WORKFLOW FOR ORDERS:
When user wants to buy products:
1. FIRST call check_stock for each product, passing the buyer's size
2. IF all are in stock in that size, call create_order with product_ids, all
   buyer details, and the size (`buyer_size`, or `sizes` when they differ per item)
3. DO NOT stop after check_stock - you MUST call create_order if in stock
4. ONLY if a product is unavailable in the requested size, say which one and
   which sizes it does have — do not order it in a size nobody asked for

RULES:
- EVERY BRIEF IS SELF-CONTAINED. Search for exactly what the current brief asks
  for, with exactly the constraints it states. Never re-apply a constraint from
  an earlier brief, never reuse an earlier product type, and never answer about
  a search that isn't the one in front of you. If an earlier search failed, that
  is irrelevant to this one — do not mention it.
- If the message is about finding/searching products → call search_catalog
- If the message mentions buying/ordering → call check_stock THEN create_order with all details
- If information is missing to call a tool (e.g., no buyer email/phone for order), ask for it
- If no products match the constraints, say so plainly and report the real price range — do
  NOT invent products, and do NOT substitute items that break a stated constraint
- When the Personal Agent pushes back ("those were too cheap", "wrong colour", "show me
  different ones"), treat that as a corrected brief: adjust the arguments it complained about,
  add the rejected IDs to exclude_ids, and search again. Do not repeat the previous call.

Response format:
- Always respond in natural language
- NEVER list individual products, prices, brands, colors, descriptions, or image
  links in your text response — the caller renders products as cards straight
  from search_catalog's structured results. Your text is just a short summary
  sentence (e.g. "Found 3 running shoes under ₹10,000:"), never an enumeration.
- Be helpful and concise"""
