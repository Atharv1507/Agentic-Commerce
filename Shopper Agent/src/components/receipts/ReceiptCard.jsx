import { motion } from "framer-motion";
import { Package, CreditCard, Loader2 } from "lucide-react";
import { Card } from "@/components/ui/card";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { orderNumber, formatOrderDate } from "./receiptUtils";

function StatusBadge({ status }) {
  if (status === "paid") return <Badge>Paid</Badge>;
  return (
    <Badge variant="secondary" className="text-muted-foreground">
      Payment pending
    </Badge>
  );
}

export default function ReceiptCard({ order, layoutId, onOpen, onPay, paying, note }) {
  const lines = order.lines || [];
  const preview = lines[0]?.name || "Order";
  const extra = lines.length - 1;
  const pending = order.status !== "paid";

  return (
    <motion.div layoutId={layoutId} whileHover={{ y: -4 }} transition={{ duration: 0.2 }}>
      <Card
        className="group cursor-pointer gap-3 border-border p-5 transition-colors hover:border-mustard/60"
        onClick={onOpen}
      >
        <div className="flex items-start justify-between gap-2">
          <div className="flex items-center gap-2.5">
            <div className="flex size-9 shrink-0 items-center justify-center rounded-full bg-mustard/20 text-foreground/70">
              <Package className="size-4" />
            </div>
            <div>
              <p className="text-sm font-semibold">Order #{orderNumber(order.order_id)}</p>
              <p className="text-xs text-muted-foreground">{formatOrderDate(order)}</p>
            </div>
          </div>
          <StatusBadge status={order.status} />
        </div>

        <p className="truncate text-sm text-foreground">
          {preview}
          {extra > 0 && <span className="text-muted-foreground"> +{extra} more</span>}
        </p>

        <div className="flex items-center justify-between border-t border-border pt-3">
          <span className="text-xs text-muted-foreground">
            {lines.length} item{lines.length === 1 ? "" : "s"}
          </span>
          <span className="text-lg font-semibold text-foreground">
            ₹{(order.amount_inr || 0).toLocaleString()}
          </span>
        </div>

        {/* An unpaid order is the one thing on this page that still needs
            doing, so it gets an action right on the card — the shopper
            shouldn't have to open a receipt to discover they can finish it.
            stopPropagation because the whole card opens the detail view. */}
        {note && (
          <p className={note.tone === "error" ? "text-xs text-destructive" : "text-xs text-muted-foreground"}>
            {note.text}
          </p>
        )}

        {pending && onPay && (
          <Button
            size="sm"
            className="w-full gap-1.5"
            disabled={paying}
            onClick={(e) => {
              e.stopPropagation();
              onPay();
            }}
          >
            {paying ? (
              <>
                <Loader2 className="size-3.5 animate-spin" /> Opening payment…
              </>
            ) : (
              <>
                <CreditCard className="size-3.5" /> Complete payment
              </>
            )}
          </Button>
        )}
      </Card>
    </motion.div>
  );
}
