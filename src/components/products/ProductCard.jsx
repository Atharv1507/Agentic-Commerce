import { motion } from "framer-motion";
import { Plus, Check } from "lucide-react";
import { cn } from "@/lib/utils";

export default function ProductCard({ product, inCart, onAddToCart }) {
  return (
    <motion.div
      className={cn(
        "group relative bg-card rounded-2xl overflow-hidden border border-border",
        "hover:border-primary/50 transition-colors"
      )}
      whileHover={{ y: -4 }}
      transition={{ duration: 0.2 }}
    >
      {/* Image placeholder */}
      <div className="aspect-[4/3] bg-secondary flex items-center justify-center overflow-hidden">
        <div className="text-6xl opacity-20">
          {product.brand?.charAt(0) || "?"}
        </div>
        <div className="absolute inset-0 bg-gradient-to-t from-card/80 to-transparent" />
      </div>

      {/* Content */}
      <div className="p-4">
        <div className="flex items-start justify-between gap-2 mb-1">
          <h3 className="font-heading text-base font-semibold leading-tight">
            {product.name}
          </h3>
        </div>

        <p className="text-sm text-muted-foreground mb-3">{product.brand}</p>

        <div className="flex items-center justify-between">
          <span className="text-lg font-semibold text-primary">
            ₹{product.price?.toLocaleString()}
          </span>

          <motion.button
            onClick={() => onAddToCart(product)}
            className={cn(
              "p-2 rounded-lg transition-colors",
              inCart
                ? "bg-primary/20 text-primary"
                : "bg-primary text-primary-foreground hover:bg-accent"
            )}
            whileHover={{ scale: 1.1 }}
            whileTap={{ scale: 0.9 }}
          >
            {inCart ? (
              <Check className="h-4 w-4" />
            ) : (
              <Plus className="h-4 w-4" />
            )}
          </motion.button>
        </div>

        {/* Color indicator */}
        {product.color && (
          <div className="mt-3 flex items-center gap-2">
            <div
              className="size-3 rounded-full border border-border"
              style={{ backgroundColor: product.color?.toLowerCase() }}
            />
            <span className="text-xs text-muted-foreground">{product.color}</span>
          </div>
        )}
      </div>
    </motion.div>
  );
}
