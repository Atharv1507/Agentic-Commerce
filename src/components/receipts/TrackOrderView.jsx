import { motion } from "framer-motion";
import { ArrowLeft, Check, Circle, Truck } from "lucide-react";
import { Button } from "@/components/ui/button";
import { cn } from "@/lib/utils";
import { orderNumber } from "./receiptUtils";

const STEPS = ["Order placed", "Packed", "Shipped", "Out for delivery", "Delivered"];

// Deterministic per order (not random per render) so revisiting the same
// order shows the same "progress" — there's no real courier integration yet,
// so this is a placeholder, but a stable one.
function stepFor(order) {
  if (order.status !== "paid") return 0;
  let hash = 0;
  for (const ch of order.order_id || "") hash = (hash * 31 + ch.charCodeAt(0)) >>> 0;
  return 1 + (hash % (STEPS.length - 1));
}

export default function TrackOrderView({ order, onBack }) {
  const current = stepFor(order);

  return (
    <motion.div
      initial={{ opacity: 0, x: 24 }}
      animate={{ opacity: 1, x: 0 }}
      exit={{ opacity: 0, x: 24 }}
      transition={{ duration: 0.25 }}
      className="flex h-full flex-col"
    >
      <div className="flex items-center gap-3 border-b border-border px-6 py-4">
        <button
          onClick={onBack}
          className="rounded-lg p-1.5 text-muted-foreground transition-colors hover:bg-secondary hover:text-foreground"
          aria-label="Back to receipt"
        >
          <ArrowLeft className="size-4" />
        </button>
        <div>
          <h2 className="font-hero text-lg">Track order</h2>
          <p className="text-xs text-muted-foreground">Order #{orderNumber(order.order_id)}</p>
        </div>
      </div>

      <div className="mx-auto flex w-full max-w-md flex-1 flex-col justify-center gap-8 px-6 py-10">
        <div className="rounded-xl border border-dashed border-border bg-secondary/40 px-4 py-3 text-center text-xs text-muted-foreground">
          Live courier tracking isn't wired up yet — this is a placeholder view.
        </div>

        <div className="flex flex-col gap-1">
          {STEPS.map((label, i) => {
            const done = i < current;
            const active = i === current;
            return (
              <div key={label} className="flex gap-3">
                <div className="flex flex-col items-center">
                  <div
                    className={cn(
                      "flex size-7 shrink-0 items-center justify-center rounded-full border-2",
                      done && "border-primary bg-primary text-primary-foreground",
                      active && "border-primary text-primary",
                      !done && !active && "border-border text-muted-foreground/50"
                    )}
                  >
                    {done ? (
                      <Check className="size-3.5" />
                    ) : active ? (
                      <Truck className="size-3.5" />
                    ) : (
                      <Circle className="size-2 fill-current" />
                    )}
                  </div>
                  {i < STEPS.length - 1 && (
                    <div className={cn("h-8 w-0.5", done ? "bg-primary" : "bg-border")} />
                  )}
                </div>
                <p
                  className={cn(
                    "pt-1 text-sm",
                    active ? "font-medium text-foreground" : done ? "text-foreground" : "text-muted-foreground"
                  )}
                >
                  {label}
                </p>
              </div>
            );
          })}
        </div>

        <Button variant="outline" onClick={onBack}>
          Back to receipt
        </Button>
      </div>
    </motion.div>
  );
}
