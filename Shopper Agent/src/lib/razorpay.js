// One place that knows how to open Razorpay Checkout, because two screens now
// need it: the chat (straight after checkout_cart) and the receipts page
// (finishing a payment the shopper walked away from). Duplicating it once meant
// duplicating every failure mode with it.

const RAZORPAY_KEY_ID = import.meta.env.VITE_RAZORPAY_KEY_ID;

/**
 * Open Razorpay Checkout for an already-created order.
 *
 * Every failure is routed to `onUnavailable` with a reason the caller can show
 * the shopper, rather than thrown. That matters because the SDK's constructor
 * THROWS synchronously on a missing key — after injecting its overlay — which
 * is what made an unset env var look like the payment window flashing open and
 * dying, with the real cause swallowed by an unrelated catch upstream.
 *
 * @param {object} order - Needs `order_id` and `amount` (PAISE, straight from
 *   the merchant; never pass rupees). `currency`, `buyer` and `product_ids`
 *   are used when present.
 * @param {object} handlers - onSuccess(paymentId, orderId), onDismiss(),
 *   onUnavailable(reason).
 * @param {object} [options] - `merchantName` for the modal's title.
 */
export function openRazorpayCheckout(order, { onSuccess, onDismiss, onUnavailable }, { merchantName } = {}) {
  if (!window.Razorpay) {
    onUnavailable("the checkout script didn't load.");
    return;
  }
  if (!RAZORPAY_KEY_ID) {
    console.error("VITE_RAZORPAY_KEY_ID is not set; cannot open Razorpay Checkout");
    onUnavailable(
      "the payment window can't open because this app has no Razorpay key configured " +
        "(set VITE_RAZORPAY_KEY_ID in Shopper Agent/.env)."
    );
    return;
  }

  try {
    const rzp = new window.Razorpay({
      key: RAZORPAY_KEY_ID,
      order_id: order.order_id,
      // Paise. The merchant's `amount` field is authoritative; `amount_inr` is
      // the one to display, and mixing them up once turned two ₹1,049 shirts
      // into "₹209,800".
      amount: order.amount ?? (order.amount_inr || 0) * 100,
      currency: order.currency || "INR",
      name: merchantName || "Checkout",
      description: `Order for ${order.product_ids?.length || order.lines?.length || 0} item(s)`,
      prefill: {
        name: order.buyer?.name || "",
        email: order.buyer?.email || "",
        contact: order.buyer?.phone || "",
      },
      theme: { color: "#5e503f" },
      handler: (paymentResponse) => {
        onSuccess(paymentResponse.razorpay_payment_id, order.order_id);
      },
      modal: { ondismiss: () => onDismiss?.() },
    });
    rzp.open();
  } catch (error) {
    console.error("Razorpay checkout failed to open", error);
    onUnavailable(`the payment window couldn't open (${error?.message || "unknown error"}).`);
  }
}
