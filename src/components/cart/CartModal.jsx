import { motion } from "framer-motion";
import { X, Trash2, ShoppingBag } from "lucide-react";
import { Button } from "@/components/ui/button";
import { ProductArt } from "@/components/products/ProductCard";
import { SIZE_ORDER, cartLineKey, cn } from "@/lib/utils";

/**
 * The size rail for one cart line, as a control rather than a label.
 *
 * Only sizes actually in stock are selectable — an out-of-stock size is shown
 * struck through and disabled rather than hidden, so the shopper can see the
 * shirt exists in L and is simply sold out, instead of wondering why L is
 * missing. Picking a size that's already in the cart merges the two lines.
 */
function LineSizePicker({ item, onChange }) {
  const sizes = item.sizes;
  if (!sizes) {
    return item.size ? (
      <span className="text-xs text-muted-foreground">Size {item.size}</span>
    ) : null;
  }

  return (
    <div className="flex flex-wrap items-center gap-1">
      {SIZE_ORDER.map((size) => {
        const count = sizes[size] ?? 0;
        const selected = item.size === size;
        const soldOut = count === 0;
        // Enough for one line but not for the quantity on it — selectable, but
        // it has to look different from a size that comfortably covers the order.
        const short = !soldOut && count < (item.quantity || 1);

        return (
          <button
            key={size}
            type="button"
            disabled={soldOut}
            onClick={() => !selected && onChange(size)}
            title={
              soldOut
                ? `Sold out in ${size}`
                : short
                  ? `Only ${count} left in ${size} — you have ${item.quantity} in your cart`
                  : `${count} in stock in ${size}`
            }
            className={cn(
              "rounded border px-1.5 py-0.5 text-[0.65rem] leading-none font-medium tracking-wide transition-colors",
              soldOut && "cursor-not-allowed border-transparent text-muted-foreground/40 line-through",
              !soldOut && !selected && "border-border text-muted-foreground hover:border-mustard hover:text-foreground",
              selected && "border-primary bg-primary text-primary-foreground",
              selected && short && "border-destructive bg-destructive"
            )}
          >
            {size}
          </button>
        );
      })}
    </div>
  );
}

// Shares layoutId="cart-shell" with FloatingCartButton — see that file for why.
export default function CartModal({ items, onClose, onConfirm, onRemove, onChangeSize }) {
  const total = items.reduce((sum, item) => sum + (item.price || 0) * (item.quantity || 1), 0);
  const units = items.reduce((sum, item) => sum + (item.quantity || 1), 0);

  // A line the shop can't fill as ordered. Surfaced here rather than only at
  // checkout: the fix is a single tap on the rail right next to it, and the
  // shopper shouldn't have to bounce off a failed checkout to discover it.
  const unfillable = items.filter((item) => {
    if (!item.sizes || !item.size) return false;
    return (item.sizes[item.size] ?? 0) < (item.quantity || 1);
  });

  return (
    <>
      <motion.div
        className="fixed inset-0 z-50 bg-foreground/40 backdrop-blur-sm"
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
          <h2 className="text-xl font-semibold">
            Your Cart
            {units > 0 && (
              <span className="ml-2 text-sm font-normal text-muted-foreground">
                {units} item{units === 1 ? "" : "s"}
              </span>
            )}
          </h2>
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
                <motion.div
                  key={cartLineKey(item)}
                  className="flex items-start gap-4 rounded-xl bg-secondary/50 p-3"
                  layout
                >
                  <ProductArt product={item} className="size-14 shrink-0 rounded-lg" />

                  <div className="flex min-w-0 flex-1 flex-col gap-2">
                    <div className="min-w-0">
                      <p className="truncate font-medium">{item.name}</p>
                      <p className="text-sm text-muted-foreground">
                        {item.brand}
                        {(item.quantity || 1) > 1 && ` · ×${item.quantity}`}
                      </p>
                    </div>
                    <LineSizePicker item={item} onChange={(size) => onChangeSize(item.id, item.size, size)} />
                  </div>

                  <div className="flex shrink-0 items-center gap-2">
                    <p className="font-semibold text-foreground">
                      ₹{((item.price || 0) * (item.quantity || 1)).toLocaleString()}
                    </p>
                    <button
                      onClick={() => onRemove(item.id, item.size)}
                      className="rounded-lg p-1.5 text-muted-foreground transition-colors hover:bg-destructive/10 hover:text-destructive"
                      aria-label={`Remove ${item.name}${item.size ? ` (${item.size})` : ""}`}
                    >
                      <Trash2 className="h-4 w-4" />
                    </button>
                  </div>
                </motion.div>
              ))}
            </div>
          )}
        </div>

        {items.length > 0 && (
          <div className="border-t border-border px-6 py-4">
            {unfillable.length > 0 && (
              <p className="mb-3 text-sm text-destructive">
                {unfillable.length === 1
                  ? `${unfillable[0].name} isn't available in ${unfillable[0].size} in that quantity.`
                  : `${unfillable.length} items aren't available in the size you picked.`}{" "}
                Pick another size above before checking out.
              </p>
            )}
            <div className="mb-4 flex items-center justify-between">
              <span className="text-muted-foreground">Total</span>
              <span className="text-xl font-semibold text-primary">₹{total.toLocaleString()}</span>
            </div>
            <div className="flex gap-3">
              <Button variant="outline" size="lg" className="flex-1 rounded-xl" onClick={onClose}>
                Close Cart
              </Button>
              <Button
                size="lg"
                className="flex-1 rounded-xl"
                onClick={onConfirm}
                disabled={unfillable.length > 0}
              >
                Proceed to Checkout
              </Button>
            </div>
          </div>
        )}
      </motion.div>
    </>
  );
}
