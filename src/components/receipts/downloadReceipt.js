import { orderNumber, formatOrderDate } from "./receiptUtils";

// A plain-text receipt, generated client-side from data already on hand — no
// backend PDF generation for what is, functionally, an itemised confirmation
// the shopper already has all the numbers for.
export function downloadReceipt(order, assistantName) {
  const lines = order.lines || [];
  const buyer = order.buyer || {};

  const rows = lines.map((item) => {
    const lineTotal = (item.price || 0) * (item.quantity || 1);
    return `${item.quantity}x  ${item.name}${item.size ? ` (${item.size})` : ""}  —  ₹${lineTotal.toLocaleString()}`;
  });

  const text = [
    `${assistantName || "Shopper Agent"} — Order Receipt`,
    "=".repeat(40),
    `Order #${orderNumber(order.order_id)}`,
    `Date: ${formatOrderDate(order)}`,
    `Status: ${order.status === "paid" ? "Paid" : "Payment pending"}`,
    order.payment_id ? `Payment ID: ${order.payment_id}` : null,
    "",
    "Items:",
    ...rows,
    "",
    `Total: ₹${(order.amount_inr || 0).toLocaleString()}`,
    "",
    "Billed to:",
    buyer.name || "",
    buyer.address || "",
    buyer.phone || "",
    buyer.email || "",
  ]
    .filter((line) => line !== null)
    .join("\n");

  const blob = new Blob([text], { type: "text/plain" });
  const url = URL.createObjectURL(blob);
  const link = document.createElement("a");
  link.href = url;
  link.download = `receipt-${orderNumber(order.order_id)}.txt`;
  link.click();
  URL.revokeObjectURL(url);
}
