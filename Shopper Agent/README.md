# Shopper Agent (Drape AI)

The only surface a human ever sees. A React chat UI that talks to the
Personal Agent for everything conversational, and to Razorpay's checkout
widget directly for the payment step itself.

## Tech stack

- **React 19** + **Vite** — dev server on `http://localhost:5173`
  (`npm run dev`), no SSR
- **Tailwind CSS v4** (via `@tailwindcss/vite`) + **shadcn/radix-ui**
  primitives for components
- **framer-motion** for screen/panel transitions, **@paper-design/shaders-react**
  for the animated background
- **react-markdown** + **remark-gfm** to render the agent's replies
- **Razorpay Checkout.js** (`window.Razorpay`, loaded separately, keyed by
  `VITE_RAZORPAY_KEY_ID`) — the actual payment UI is Razorpay's own modal,
  not a custom form
- No backend of its own, no database — all state either lives in the
  Personal Agent's session store or in local React state for the current tab

## Flow

1. `useSession` — onboarding (or skip) → `POST /onboarding`, then
   `GET /session/{email}` to hydrate profile/preferences/cart on return
   visits.
2. `useChatThreads` — one conversation per "chat" the shopper opens; switching
   threads is purely a `thread_id` change on every subsequent call, so the
   Personal Agent's per-thread memory lines up with what's on screen.
3. `useChat` — sends each message to `/chat/stream` first (SSE), rendering
   the backend's own progress narration ("Asking the seller about...",
   "Round 2: pushing the seller for closer matches"...) while it waits;
   falls back to the blocking `/chat` endpoint if streaming isn't available.
   The response can carry structured `products`, `cart`, `profile` or a
   `form` (the "narrow this down" chip picker) alongside the reply text.
4. Checkout: when the agent's tool result includes an order, `openRazorpay`
   opens Razorpay's modal client-side with that order's id/amount. On
   success, the payment id + order id are sent back to the agent as a chat
   message, which triggers `verify_payment` on the Personal Agent and a
   receipt. The order itself is created by the merchant, not the Personal
   Agent — the amount in the modal is the merchant's price, campaign discount
   already applied.
5. Merchant offers arrive as an `offers` array on a chat response and render as
   their own "Offer from the shop" message, above any cross-sell. The wording
   is the merchant's own and is shown verbatim — the saving is the shop's
   promise, not the assistant's to restate.
6. Cart edits (add/remove/resize) can happen two ways: the shopper clicking a
   product card (straight `POST/PATCH/DELETE /cart/...` calls, instant, no
   LLM involved) or the agent doing it mid-conversation (comes back as a
   `cart` field on the chat response) — `useChat` reconciles whichever
   arrives last.

## Endpoints

This app exposes none — it's a static SPA. It only calls out to:

| Service | What for |
|---|---|
| Personal Agent (`VITE_API_BASE_URL`, default `http://localhost:8000`) | Every `/onboarding`, `/session/*`, `/cart/*`, `/chat`, `/chat/stream` call |
| Razorpay Checkout.js | The payment modal itself, using the order the merchant already created |
| Seller Agent (`VITE_SELLER_BASE_URL`, default `http://localhost:8001`) | **Only** `GET /merchant/analytics`, for the developer-only merchant dashboard |

No shopping traffic touches the Seller Agent — the merchant dashboard is the
single exception, and it's a developer affordance rather than a shopper
feature (see below).

## Merchant dashboard (developer only)

The chart icon at the bottom of the sidebar opens `MerchantDashboard`, a
full-screen view of the *merchant's* books: revenue, AOV, **revenue attributed
per buyer agent**, cross-sell attach rate, campaign impact and top products. A
real shopper would never see this; it exists to make the growth side of the
system visible in a demo.

It reads the Seller Agent directly, because those numbers belong to the shop —
deriving them from this shopper's own session would only ever show revenue that
this one buyer agent brought in, which is precisely the blind spot the merchant
needs to see past.

`VITE_MERCHANT_KEY` ships in the client bundle and is therefore **not secret**.
That's tolerable here only because the endpoint it opens is read-only and this
is an explicitly developer-facing button. The production shape would be a
merchant-authenticated session behind a backend of its own.

Charts are hand-rolled CSS bars rather than a charting library: the app has no
chart dependency, one bar per row is all this needs, and a library would bring
its own type scale and colour defaults to fight with the theme — the same
reasoning behind `TrackOrderView`'s hand-built timeline.

## Communication flow

```
Shopper (browser)
     │
     ▼
Shopper Agent (React/Vite, :5173)
     │  fetch, JSON / SSE
     ▼
Personal Agent (:8000)  ──▶  Seller Agent (:8001), Razorpay API, OpenAI
     ▲
     │  Razorpay Checkout.js modal (loaded client-side)
     │
Shopper (browser) ──▶ Razorpay's own hosted payment UI directly
```

The browser touches two things over the network: the Personal Agent, and
Razorpay's payment widget. Everything else (catalogue negotiation, order
creation, payment verification) happens server-side.
