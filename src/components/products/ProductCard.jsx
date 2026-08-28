import { motion } from "framer-motion";
import { Plus, Check } from "lucide-react";
import { Card } from "@/components/ui/card";
import { cn } from "@/lib/utils";

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
          : "linear-gradient(160deg, var(--color-secondary) 0%, var(--color-card) 100%)",
      }}
    >
      <span className="font-hero text-6xl text-white/10">{product.brand?.charAt(0) || "?"}</span>
    </div>
  );
}

export default function ProductCard({ product, inCart, onAddToCart, onOpen, layoutId }) {
  return (
    <motion.div layoutId={layoutId} whileHover={{ y: -4 }} transition={{ duration: 0.2 }}>
      <Card
        className="group relative cursor-pointer gap-0 overflow-hidden border-border p-0 transition-colors hover:border-primary/50"
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
          <p className="mb-3 text-sm text-muted-foreground">{product.brand}</p>

          <div className="flex items-center justify-between">
            <span className="text-lg font-semibold text-primary">₹{product.price?.toLocaleString()}</span>

            <motion.button
              onClick={(e) => {
                e.stopPropagation();
                onAddToCart(product);
              }}
              className={cn(
                "rounded-lg p-2 transition-colors",
                inCart ? "bg-primary/20 text-primary" : "bg-primary text-primary-foreground hover:bg-accent"
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
