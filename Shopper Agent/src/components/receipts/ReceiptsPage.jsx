import { useEffect, useState } from "react";
import { createPortal } from "react-dom";
import { motion, AnimatePresence } from "framer-motion";
import { ArrowLeft, X, PackageOpen, Download, Truck, CreditCard, Loader2, ExternalLink } from "lucide-react";
import { Button } from "@/components/ui/button";
import { cn } from "@/lib/utils";
import useOrders from "@/hooks/useOrders";
import ReceiptCard from "./ReceiptCard";
import { orderNumber, formatOrderDate } from "./receiptUtils";
import TrackOrderView from "./TrackOrderView";
import { downloadReceipt } from "./downloadReceipt";

// A dedicated full-screen section rather than a small dialog — a grid of past
// orders and an expanded receipt with line items need real room, the same
// reason the chat's product results get a grid instead of a list.
// The expand interaction mirrors ProductGrid's click-to-lightbox pattern:
// a shared framer-motion layoutId carries the card into a focused view.
function ReceiptDetail({ order, onDownload, onTrack, onPay, paying, note }) {
  const lines = order.lines || [];
  const pending = order.status !== "paid";

  return (
    <motion.div
      key="detail"
      initial={{ opacity: 0 }}
      animate={{ opacity: 1 }}
      exit={{ opacity: 0 }}
      transition={{ duration: 0.15 }}
      className="flex max-h-[85vh] flex-col"
    >
      <div className="flex items-start justify-between gap-4 border-b border-border px-6 py-5">
        <div>
          <p className="text-xs tracking-widest text-muted-foreground uppercase">
            {order.status === "paid" ? "Paid" : "Payment pending"}
          </p>
          <h2 className="font-hero mt-1 text-xl">Order #{orderNumber(order.order_id)}</h2>
          <p className="text-sm text-muted-foreground">{formatOrderDate(order)}</p>
        </div>
      </div>

      <div className="flex-1 overflow-y-auto px-6 py-4">
        <div className="flex flex-col divide-y divide-border">
          {lines.map((item, i) => (
            <div key={`${item.id}-${item.size}-${i}`} className="flex items-center justify-between gap-3 py-3">
              <div className="min-w-0">
                <p className="truncate text-sm font-medium">{item.name}</p>
                <p className="text-xs text-muted-foreground">
                  {item.brand ? `${item.brand} · ` : ""}
                  {item.size ? `Size ${item.size} · ` : ""}Qty {item.quantity}
                </p>
              </div>
              <span className="shrink-0 text-sm font-medium">
                ₹{((item.price || 0) * (item.quantity || 1)).toLocaleString()}
              </span>
            </div>
          ))}
        </div>

        {order.buyer?.address && (
          <div className="mt-4 rounded-xl bg-secondary/40 p-3 text-xs text-muted-foreground">
            <p className="mb-1 font-medium text-foreground">Delivered to</p>
            <p>{order.buyer.name}</p>
            <p>{order.buyer.address}</p>
            <p>{order.buyer.phone}</p>
          </div>
        )}
      </div>

      <div className="flex items-center justify-between border-t border-border px-6 py-4">
        <span className="text-sm text-muted-foreground">Total</span>
        <span className="text-xl font-semibold text-primary">
          ₹{(order.amount_inr || 0).toLocaleString()}
        </span>
      </div>

      {note && (
        <p
          className={cn(
            "px-6 pb-1 text-xs",
            note.tone === "error" ? "text-destructive" : "text-muted-foreground"
          )}
        >
          {note.text}
        </p>
      )}

      <div className="flex flex-col gap-2 px-6 pb-6">
        <div className="flex gap-2">
          <Button variant="outline" className="flex-1 gap-2" onClick={onDownload}>
            <Download className="size-4" /> Download receipt
          </Button>
          {/* Tracking an order nobody has paid for tells the shopper nothing,
              so the pending state offers the action that actually moves it
              forward instead. Same order at the merchant, same amount — this
              reopens payment for it rather than creating a second one. */}
          {pending ? (
            <Button className="flex-1 gap-2" disabled={paying} onClick={onPay}>
              {paying ? (
                <>
                  <Loader2 className="size-4 animate-spin" /> Opening payment…
                </>
              ) : (
                <>
                  <CreditCard className="size-4" /> Pay ₹{(order.amount_inr || 0).toLocaleString()}
                </>
              )}
            </Button>
          ) : (
            <Button className="flex-1 gap-2" onClick={onTrack}>
              <Truck className="size-4" /> Track order
            </Button>
          )}
        </div>

        {/* The merchant's browser-free payment page for this same order. Shown
            as a way out when the in-app modal won't open at all — an order the
            shopper can't pay is the failure worth a second route. */}
        {pending && order.payment_url && (
          <a
            href={order.payment_url}
            target="_blank"
            rel="noopener noreferrer"
            className="inline-flex items-center justify-center gap-1.5 text-xs text-muted-foreground underline-offset-4 hover:text-foreground hover:underline"
          >
            <ExternalLink className="size-3" /> Or pay on the shop's secure page
          </a>
        )}
      </div>
    </motion.div>
  );
}

export default function ReceiptsPage({ session, onClose }) {
  const { orders, payOrder, payingId, payErrors } = useOrders(session, true);
  const [selectedIndex, setSelectedIndex] = useState(null);
  const [tracking, setTracking] = useState(false);
  const isOpen = selectedIndex !== null;
  const selected = isOpen ? orders?.[selectedIndex] : null;

  // Closes the lightbox and clears tracking in one step, rather than reacting
  // to selectedIndex becoming null in a separate effect — the two states are
  // both "which detail view is showing", so they change together.
  const closeDetail = () => {
    setSelectedIndex(null);
    setTracking(false);
  };

  useEffect(() => {
    const handleKeyDown = (e) => {
      if (e.key !== "Escape") return;
      if (isOpen) {
        setSelectedIndex(null);
        setTracking(false);
      } else {
        onClose();
      }
    };
    window.addEventListener("keydown", handleKeyDown);
    return () => window.removeEventListener("keydown", handleKeyDown);
  }, [isOpen, onClose]);

  return (
    <motion.div
      className="fixed inset-0 z-[70] flex flex-col bg-background"
      initial={{ opacity: 0 }}
      animate={{ opacity: 1 }}
      exit={{ opacity: 0 }}
      transition={{ duration: 0.2 }}
    >
      <div className="flex items-center gap-3 border-b border-border px-6 py-4 md:px-10">
        <button
          onClick={onClose}
          className="rounded-lg p-1.5 text-muted-foreground transition-colors hover:bg-secondary hover:text-foreground"
          aria-label="Back to chat"
        >
          <ArrowLeft className="size-4" />
        </button>
        <h1 className="font-hero text-xl">Your orders</h1>
      </div>

      <div className="flex-1 overflow-y-auto">
        {orders === null ? (
          <p className="p-10 text-center text-sm text-muted-foreground">Loading your orders…</p>
        ) : orders.length === 0 ? (
          <div className="flex h-full flex-col items-center justify-center gap-3 p-10 text-center">
            <PackageOpen className="size-8 text-muted-foreground/50" />
            <p className="max-w-xs text-sm text-muted-foreground">
              No orders yet. Once you check out, your receipts will show up here.
            </p>
          </div>
        ) : (
          <div className="grid grid-cols-1 gap-4 p-6 sm:grid-cols-2 lg:grid-cols-3 md:px-10">
            {orders.map((order, i) => (
              <motion.div
                key={order.order_id}
                initial={{ opacity: 0, y: 20 }}
                animate={{ opacity: 1, y: 0 }}
                transition={{ delay: i * 0.05 }}
              >
                <ReceiptCard
                  order={order}
                  layoutId={`receipt-card-${order.order_id}`}
                  onOpen={() => setSelectedIndex(i)}
                  onPay={() => payOrder(order)}
                  paying={payingId === order.order_id}
                  note={payErrors[order.order_id]}
                />
              </motion.div>
            ))}
          </div>
        )}
      </div>

      {createPortal(
        <AnimatePresence>
          {isOpen && (
            <motion.div
              className="fixed inset-0 z-[80] flex items-center justify-center bg-foreground/50 p-6 backdrop-blur-sm"
              initial={{ opacity: 0 }}
              animate={{ opacity: 1 }}
              exit={{ opacity: 0 }}
              onClick={closeDetail}
            >
              <motion.div
                layoutId={`receipt-card-${selected.order_id}`}
                className="relative w-full max-w-2xl overflow-hidden rounded-2xl bg-card"
                onClick={(e) => e.stopPropagation()}
              >
                <AnimatePresence mode="wait">
                  {tracking ? (
                    <TrackOrderView order={selected} onBack={() => setTracking(false)} />
                  ) : (
                    <ReceiptDetail
                      order={selected}
                      onDownload={() => downloadReceipt(selected, session?.assistantName)}
                      onTrack={() => setTracking(true)}
                      onPay={() => payOrder(selected)}
                      paying={payingId === selected.order_id}
                      note={payErrors[selected.order_id]}
                    />
                  )}
                </AnimatePresence>

                {!tracking && (
                  <button
                    onClick={closeDetail}
                    className="absolute top-4 right-4 rounded-full bg-background/85 p-2 text-foreground shadow-sm backdrop-blur-sm transition-colors hover:bg-background"
                  >
                    <X className="size-4" />
                  </button>
                )}
              </motion.div>
            </motion.div>
          )}
        </AnimatePresence>,
        document.body
      )}
    </motion.div>
  );
}
