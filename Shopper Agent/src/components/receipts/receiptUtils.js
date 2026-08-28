// A short, human order number rather than the full Razorpay ID — the shopper
// never needs the whole "order_Nxyz..." string, just something to reference.
export function orderNumber(orderId) {
  return (orderId || "").slice(-8).toUpperCase();
}

export function formatOrderDate(order) {
  const ts = order.paid_at || order.created_at;
  if (!ts) return "";
  return new Date(ts * 1000).toLocaleDateString(undefined, {
    day: "numeric",
    month: "short",
    year: "numeric",
  });
}
