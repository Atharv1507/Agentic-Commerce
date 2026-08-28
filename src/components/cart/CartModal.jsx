import { motion } from "framer-motion";
import { X, Trash2, ShoppingBag } from "lucide-react";
import { Button } from "@/components/ui/button";

// Shares layoutId="cart-shell" with FloatingCartButton — see that file for why.
export default function CartModal({ items, onClose, onConfirm, onRemove }) {
  const total = items.reduce((sum, item) => sum + (item.price || 0), 0);

  return (
    <>
      <motion.div
        className="fixed inset-0 z-50 bg-black/60 backdrop-blur-sm"
        initial={{ opacity: 0 }}
        animate={{ opacity: 1 }}
        exit={{ opacity: 0 }}
        onClick={onClose}
      />

      <motion.div
        layoutId="cart-shell"
        className="fixed inset-x-0 bottom-0 z-50 flex max-h-[80vh] flex-col rounded-t-2xl border-t border-border bg-card"
      >
        <div className="flex items-center justify-between border-b border-border px-6 py-4">
          <h2 className="text-xl font-semibold">Your Cart</h2>
          <button onClick={onClose} className="rounded-lg p-2 transition-colors hover:bg-secondary" aria-label="Close cart">
            <X className="h-5 w-5" />
          </button>
        </div>

        <div className="flex-1 overflow-y-auto px-6 py-4">
          {items.length === 0 ? (
            <div className="flex flex-col items-center justify-center py-12 text-muted-foreground">
              <ShoppingBag className="mb-4 h-12 w-12 opacity-50" />
              <p>Your cart is empty</p>
            </div>
          ) : (
            <div className="flex flex-col gap-3">
              {items.map((item) => (
                <motion.div key={item.id} className="flex items-center gap-4 rounded-xl bg-secondary/50 p-3" layout>
                  <div className="flex size-12 items-center justify-center rounded-lg bg-secondary text-lg font-semibold text-muted-foreground">
                    {item.brand?.charAt(0) || "?"}
                  </div>
                  <div className="min-w-0 flex-1">
                    <p className="truncate font-medium">{item.name}</p>
                    <p className="text-sm text-muted-foreground">{item.brand}</p>
                  </div>
                  <p className="font-semibold text-primary">₹{item.price?.toLocaleString()}</p>
                  <button
                    onClick={() => onRemove(item.id)}
                    className="rounded-lg p-1.5 text-muted-foreground transition-colors hover:bg-destructive/10 hover:text-destructive"
                  >
                    <Trash2 className="h-4 w-4" />
                  </button>
                </motion.div>
              ))}
            </div>
          )}
        </div>

        {items.length > 0 && (
          <div className="border-t border-border px-6 py-4">
            <div className="mb-4 flex items-center justify-between">
              <span className="text-muted-foreground">Total</span>
              <span className="text-xl font-semibold text-primary">₹{total.toLocaleString()}</span>
            </div>
            <div className="flex gap-3">
              <Button variant="outline" size="lg" className="flex-1 rounded-xl" onClick={onClose}>
                Close Cart
              </Button>
              <Button size="lg" className="flex-1 rounded-xl" onClick={onConfirm}>
                Proceed to Checkout
              </Button>
            </div>
          </div>
        )}
      </motion.div>
    </>
  );
}
