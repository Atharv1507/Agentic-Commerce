import { motion } from "framer-motion";
import { Package } from "lucide-react";
import { Card } from "@/components/ui/card";
import { Badge } from "@/components/ui/badge";
import { orderNumber, formatOrderDate } from "./receiptUtils";

function StatusBadge({ status }) {
  if (status === "paid") return <Badge>Paid</Badge>;
  return (
    <Badge variant="secondary" className="text-muted-foreground">
      Payment pending
    </Badge>
  );
}

export default function ReceiptCard({ order, layoutId, onOpen }) {
  const lines = order.lines || [];
  const preview = lines[0]?.name || "Order";
  const extra = lines.length - 1;

  return (
    <motion.div layoutId={layoutId} whileHover={{ y: -4 }} transition={{ duration: 0.2 }}>
      <Card
        className="group cursor-pointer gap-3 border-border p-5 transition-colors hover:border-primary/50"
        onClick={onOpen}
      >
        <div className="flex items-start justify-between gap-2">
          <div className="flex items-center gap-2.5">
            <div className="flex size-9 shrink-0 items-center justify-center rounded-full bg-primary/15 text-primary">
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
          <span className="text-lg font-semibold text-primary">
            ₹{(order.amount_inr || 0).toLocaleString()}
          </span>
        </div>
      </Card>
    </motion.div>
  );
}
