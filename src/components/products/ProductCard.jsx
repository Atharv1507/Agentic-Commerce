import { motion } from "framer-motion";
import { Plus, Check } from "lucide-react";
import { Card } from "@/components/ui/card";
import { SIZE_ORDER, cn, resolveCartSize } from "@/lib/utils";

// Real product photos take over here; the color-tinted gradient tile with the
// brand's initial only stands in when a product has no image to show.
export function ProductArt({ product, className }) {
  if (product.image) {
    return (
      <div className={cn("relative overflow-hidden bg-secondary", className)}>
        <img src={product.image} alt={product.name} className="size-full object-cover" loading="lazy" />
      </div>
    );
  }

  const tint = product.color?.toLowerCase();
  return (
    <div
      className={cn("relative flex items-center justify-center overflow-hidden bg-secondary", className)}
      style={{
        backgroundImage: tint
          ? `radial-gradient(120% 120% at 20% 15%, ${tint}33 0%, transparent 55%), linear-gradient(160deg, var(--color-secondary) 0%, var(--color-card) 100%)`
          : "linear-gradient(160deg, var(--color-secondary) 0%, var(--color-card) 10%)",
      }}
    >
      <span className="font-hero text-6xl text-foreground/10">{product.brand?.charAt(0) || "?"}</span>
    </div>
  );
}

/**
 * Which sizes this product can be had in, out-of-stock ones included.
 *
 * Showing the gaps is the point. A rail listing only what's available reads as
 * "we have four sizes"; one that strikes through the missing two reads as
 * "sold out in L", which is the thing the shopper actually needs to know.
 */
export function SizeRail({ product, userSize, showCounts = false, className }) {
  const sizes = product?.sizes;
  if (!sizes) return null;

  return (
    <div className={cn("flex flex-wrap items-center gap-1.5", className)}>
      {SIZE_ORDER.map((size) => {
        const count = sizes[size] ?? 0;
        const isMine = userSize === size;
        return (
          <span
            key={size}
            title={
              count === 0
                ? `Out of stock in ${size}`
                : `${count} left in ${size}${isMine ? " — your size" : ""}`
            }
            className={cn(
              "rounded border px-1.5 py-0.5 text-[0.65rem] leading-none font-medium tracking-wide",
              count === 0
                ? "border-transparent text-muted-foreground/45 line-through"
                : "border-border text-foreground",
              isMine && count > 0 && "border-mustard bg-mustard/15 text-foreground"
            )}
          >
            {size}
            {showCounts && count > 0 && (
              <span className="ml-1 font-normal text-muted-foreground">{count}</span>
            )}
          </span>
        );
      })}
    </div>
  );
}

export default function ProductCard({ product, inCart, onAddToCart, onOpen, layoutId, userSize }) {
  // Which size the quick-add would use. Named here so the button can say so on
  // hover — a one-click add that silently picks a size the shopper didn't ask
  // for is the thing worth being explicit about.
  const quickSize = resolveCartSize(product, userSize);

  return (
    <motion.div layoutId={layoutId} whileHover={{ y: -4 }} transition={{ duration: 0.2 }}>
      <Card
        className="group relative cursor-pointer gap-0 overflow-hidden border-border p-0 transition-colors hover:border-mustard/60"
        onClick={onOpen}
      >
        <div className="relative aspect-[4/3]">
          <ProductArt product={product} className="absolute inset-0" />
          <div
            className="pointer-events-none absolute inset-0 bg-gradient-to-t from-card/90 to-transparent"
            style={{ maskImage: "linear-gradient(to top, black 25%, transparent 55%)" }}
          />
        </div>

        <div className="p-4">
          <h3 className="text-base leading-tight font-semibold">{product.name}</h3>
          <p className="text-sm text-muted-foreground">{product.brand}</p>

          <SizeRail product={product} userSize={userSize} className="my-3" />

          <div className="flex items-center justify-between">
            <span className="text-lg font-semibold text-foreground">₹{product.price?.toLocaleString()}</span>

            <motion.button
              onClick={(e) => {
                e.stopPropagation();
                onAddToCart(product);
              }}
              title={
                quickSize
                  ? `${inCart ? "Remove" : "Add"} ${quickSize}${
                      userSize && quickSize !== userSize ? " (your size is unavailable)" : ""
                    }`
                  : "Sold out in every size"
              }
              disabled={!quickSize}
              className={cn(
                "rounded-lg p-2 transition-colors",
                inCart ? "bg-primary/20 text-primary" : "bg-primary text-primary-foreground hover:bg-sand hover:text-sand-foreground"
              )}
              whileHover={{ scale: 1.1 }}
              whileTap={{ scale: 0.9 }}
            >
              {inCart ? <Check className="h-4 w-4" /> : <Plus className="h-4 w-4" />}
            </motion.button>
          </div>
        </div>
      </Card>
    </motion.div>
  );
}
