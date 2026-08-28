import { TriangleAlert } from "lucide-react";
import {
  Dialog,
  DialogContent,
  DialogHeader,
  DialogTitle,
  DialogDescription,
  DialogFooter,
} from "@/components/ui/dialog";
import { Button } from "@/components/ui/button";

// Shown when checkout_cart is blocked by the shopper's own auto-approve spend
// limit. This is a plain business-rule gate, separate from the Razorpay
// payment modal — no order exists yet at this point, so there's nothing for
// Razorpay to open. Confirming here is what lets an order get created at all.
export default function SpendLimitDialog({ open, onOpenChange, amountInr, spendLimit, onConfirm, onCancel }) {
  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className="border-border bg-card text-card-foreground sm:max-w-sm">
        <DialogHeader>
          <div className="flex items-center gap-2.5">
            <TriangleAlert className="size-5 shrink-0 text-destructive" />
            <DialogTitle className="font-hero text-lg font-medium">Over your spend limit</DialogTitle>
          </div>
          <DialogDescription>
            This order is ₹{amountInr?.toLocaleString()}, above your ₹{spendLimit?.toLocaleString()}{" "}
            auto-approve limit. You can raise this limit any time in Settings.
          </DialogDescription>
        </DialogHeader>

        <DialogFooter>
          <Button variant="outline" onClick={onCancel}>
            Cancel
          </Button>
          <Button variant="destructive" onClick={onConfirm}>
            Confirm anyway
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}
