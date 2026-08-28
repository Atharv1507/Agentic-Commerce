import { useEffect, useState } from "react";

const API_BASE = import.meta.env.VITE_API_BASE_URL || "http://localhost:8000";

// Fetches fresh every time the receipts page opens — order status can change
// between visits (a payment confirming after the shopper closed the app), so
// there's no value in caching across opens.
export default function useOrders(session, open) {
  const [orders, setOrders] = useState(null);

  useEffect(() => {
    if (!open || !session?.email) return;
    let active = true;

    fetch(`${API_BASE}/session/${session.email}/orders`)
      .then((res) => (res.ok ? res.json() : { orders: [] }))
      .then((data) => active && setOrders(data.orders || []))
      .catch(() => active && setOrders([]));

    return () => {
      active = false;
    };
  }, [open, session?.email]);

  return { orders };
}
