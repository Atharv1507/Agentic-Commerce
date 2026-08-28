import { useEffect, useState } from "react";

// The merchant's own service, not the Personal Agent. These numbers are the
// SHOP's books, and the shop is the only party that can total them — deriving
// them from this shopper's session would only ever show revenue this one buyer
// agent brought in, which is exactly the blind spot the merchant needs to see
// past now that several buyer agents can transact with it.
const SELLER_BASE = import.meta.env.VITE_SELLER_BASE_URL || "http://localhost:8001";

// Demo-only. This key ships in the client bundle, so it is not meaningfully
// secret — acceptable for a developer button behind which nothing can be
// mutated (the endpoint is read-only), and NOT the production shape, which
// would put a merchant-authenticated session behind a backend of its own.
const MERCHANT_KEY = import.meta.env.VITE_MERCHANT_KEY || "demo-merchant-key";

// No `open` argument and no state reset: the dashboard is mounted fresh by
// AnimatePresence each time it opens and unmounted when it closes, so this
// hook's state starts empty on every visit anyway. Revenue moves as orders are
// paid, so each mount refetches.
export default function useMerchantAnalytics() {
  const [analytics, setAnalytics] = useState(null);
  const [error, setError] = useState(null);

  useEffect(() => {
    let active = true;

    fetch(`${SELLER_BASE}/merchant/analytics`, {
      headers: { "X-Merchant-Key": MERCHANT_KEY },
    })
      .then((res) => {
        if (!res.ok) throw new Error(res.status === 401 ? "unauthorised" : `http ${res.status}`);
        return res.json();
      })
      .then((data) => active && setAnalytics(data))
      // Distinguished from an empty shop on purpose: "the merchant service
      // isn't running" and "nothing has sold yet" look identical if both
      // render as zeroes, and only one of them is something to go fix.
      .catch((e) => active && setError(e.message));

    return () => {
      active = false;
    };
  }, []);

  return { analytics, error };
}
