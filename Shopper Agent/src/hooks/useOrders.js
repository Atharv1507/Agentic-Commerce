import { useCallback, useEffect, useState } from "react";
import { openRazorpayCheckout } from "@/lib/razorpay";

const API_BASE = import.meta.env.VITE_API_BASE_URL || "http://localhost:8000";

/**
 * Read this account's orders. Returns null when the backend couldn't be
 * reached — distinct from an empty list, which means "no orders".
 */
async function fetchOrders(email) {
  if (!email) return [];
  try {
    const res = await fetch(`${API_BASE}/session/${email}/orders`);
    if (!res.ok) return [];
    const data = await res.json();
    return data.orders || [];
  } catch {
    return null;
  }
}

// Fetches fresh every time the receipts page opens — order status can change
// between visits (a payment confirming after the shopper closed the app), so
// there's no value in caching across opens.
export default function useOrders(session, open) {
  const [orders, setOrders] = useState(null);
  // Which order the shopper is currently paying, so its button can show it and
  // a second click can't open two checkouts for the same order.
  const [payingId, setPayingId] = useState(null);
  // Per-order message from the last payment attempt, keyed by order_id:
  // { tone: "error" | "info", text }. Kept here rather than in the page so it
  // survives closing and reopening the receipt detail.
  const [payErrors, setPayErrors] = useState({});

  const email = session?.email;

  // Kept separate from the state write below: the effect needs to discard a
  // result that arrived after unmount, and `refresh` needs the fresh list to
  // act on without waiting a render. Neither works if fetching and storing are
  // the same call.
  const load = useCallback(async () => {
    const fetched = await fetchOrders(email);
    if (fetched) setOrders(fetched);
    return fetched || [];
  }, [email]);

  useEffect(() => {
    if (!open || !email) return;
    let active = true;
    fetchOrders(email).then((fetched) => {
      // An unreachable backend is not evidence the shopper has no orders, so
      // fetchOrders returns null for "don't know" and whatever is on screen
      // stays there.
      if (active && fetched) setOrders(fetched);
      else if (active) setOrders((prev) => prev ?? []);
    });
    return () => {
      active = false;
    };
  }, [open, email]);

  const setNote = useCallback((orderId, tone, text) => {
    setPayErrors((prev) => ({ ...prev, [orderId]: text ? { tone, text } : undefined }));
  }, []);

  /**
   * Finish paying an order that was created but never paid.
   *
   * The order already exists at the merchant with its amount fixed, so this
   * reopens Razorpay against that same `order_id` rather than creating a second
   * one — checking out again would leave the shopper with two orders and only
   * one of them wanted.
   *
   * Confirmation goes through the dedicated verify route instead of the chat:
   * this button knows exactly which order it just paid, and shouldn't depend on
   * the model reading a sentence about it to record the fact.
   */
  const payOrder = useCallback(
    (order) => {
      if (!order?.order_id || payingId) return;
      setPayingId(order.order_id);
      setNote(order.order_id, null, null);

      const done = () => setPayingId(null);

      openRazorpayCheckout(
        order,
        {
          onSuccess: async (paymentId, orderId) => {
            try {
              const res = await fetch(
                `${API_BASE}/session/${email}/orders/${orderId}/verify`,
                {
                  method: "POST",
                  headers: { "Content-Type": "application/json" },
                  body: JSON.stringify({ payment_id: paymentId }),
                }
              );
              if (!res.ok) throw new Error(`verify failed (${res.status})`);
              const data = await res.json();
              await load();
              // Razorpay's handler firing is not the same as the merchant
              // agreeing it was paid, and only the merchant's answer settles
              // the order — so the shopper is told which one they got.
              if (!["paid", "captured"].includes(data.payment?.status)) {
                setNote(
                  orderId,
                  "info",
                  "Payment received — waiting on the shop to confirm it. Refresh in a moment."
                );
              }
            } catch (error) {
              console.error("Could not confirm the payment", error);
              // The money may well have moved; saying otherwise would be worse
              // than saying we don't know yet.
              setNote(
                orderId,
                "info",
                `Payment went through (${paymentId}) but we couldn't confirm it with the shop. It'll show as paid once confirmed — don't pay again.`
              );
              await load();
            } finally {
              done();
            }
          },
          onDismiss: () => {
            setNote(order.order_id, "info", "Payment window closed. This order is still unpaid.");
            done();
          },
          onUnavailable: (reason) => {
            setNote(
              order.order_id,
              "error",
              order.payment_url
                ? `Couldn't open the payment window — ${reason} Use the payment link below instead.`
                : `Couldn't open the payment window — ${reason}`
            );
            done();
          },
        },
        { merchantName: session?.assistantName }
      );
    },
    [email, payingId, session?.assistantName, load, setNote]
  );

  return { orders, refresh: load, payOrder, payingId, payErrors };
}
