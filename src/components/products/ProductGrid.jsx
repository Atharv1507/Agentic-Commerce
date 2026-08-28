import { useState, useEffect } from "react";
import { createPortal } from "react-dom";
import { motion, AnimatePresence } from "framer-motion";
import { X, ChevronLeft, ChevronRight, Plus, Check } from "lucide-react";
import ProductCard, { ProductArt } from "./ProductCard";
import { Button } from "@/components/ui/button";
import { SIZE_ORDER, cn, resolveCartSize } from "@/lib/utils";

// Click a card and it expands in place into a focused view — siblings dim to the
// sides, swipe or use the arrow keys to move between results, close to return to
// the grid. Modeled on the click-to-lightbox interaction from the Framer reference,
// rebuilt with framer-motion shared layout animations since our data has a single
// image per product rather than the reference's multi-image/variant model.
// `gridId` scopes the shared-layout ids to this grid instance. framer-motion
// treats a layoutId as global, so when the same product appeared in two
// messages both cards claimed one id and framer animated the card out of the
// older message and into the newer one — the card visibly flew down the
// transcript. Namespacing by message keeps the click-to-expand animation while
// making each grid's cards independent.
// The one line of size copy worth spending space on: whether the shopper's own
// size is there, and whether it's about to run out. Everything else the rail
// already says visually.
function SizeNote({ product, userSize, chosenSize }) {
  if (!product.sizes) return null;

  // The shopper's own size is the one worth calling out by name — if it isn't
  // there, that's the headline, whatever they happen to have selected.
  if (userSize && (product.sizes[userSize] ?? 0) === 0) {
    const other = (product.available_sizes || []).join(", ");
    return (
      <p className="mt-2 text-sm text-destructive">
        Not available in your size ({userSize}).
        {other ? ` In stock in ${other}.` : " Sold out in every size."}
      </p>
    );
  }

  if (!chosenSize) return null;
  const count = product.sizes[chosenSize] ?? 0;
  const mine = chosenSize === userSize;

  if (count <= 2) {
    return (
      <p className="mt-2 text-sm text-primary">
        Only {count} left in {chosenSize}
        {mine ? " — your size" : ""}.
      </p>
    );
  }
  return (
    <p className="mt-2 text-sm text-muted-foreground">
      In stock in {chosenSize}
      {mine ? " — your size" : ""}.
    </p>
  );
}

export default function ProductGrid({ products, cart, onAddToCart, gridId = "grid", userSize }) {
  const [selectedIndex, setSelectedIndex] = useState(null);
  // Which size the lightbox is currently offering to add. Null until a product
  // is open, then seeded from the shopper's own size so the common case is one
  // click — but it stays a visible, changeable choice rather than an
  // assumption buried in the Add button.
  const [chosenSize, setChosenSize] = useState(null);
  const isOpen = selectedIndex !== null;
  const selected = isOpen ? products[selectedIndex] : null;

  useEffect(() => {
    setChosenSize(selected ? resolveCartSize(selected, userSize) : null);
  }, [selected, userSize]);

  useEffect(() => {
    if (!isOpen) return;
    const handleKeyDown = (e) => {
      if (e.key === "Escape") setSelectedIndex(null);
      else if (e.key === "ArrowRight") setSelectedIndex((i) => Math.min(i + 1, products.length - 1));
      else if (e.key === "ArrowLeft") setSelectedIndex((i) => Math.max(i - 1, 0));
    };
    window.addEventListener("keydown", handleKeyDown);
    return () => window.removeEventListener("keydown", handleKeyDown);
  }, [isOpen, products.length]);

  return (
    <>
      <motion.div
        className="grid grid-cols-1 gap-4 p-4 sm:grid-cols-2 lg:grid-cols-3"
        initial={{ opacity: 0 }}
        animate={{ opacity: 1 }}
        transition={{ duration: 0.3 }}
      >
        {products.map((product, i) => (
          <motion.div
            key={product.id}
            initial={{ opacity: 0, y: 20 }}
            animate={{ opacity: 1, y: 0 }}
            transition={{ delay: i * 0.05 }}
          >
            <ProductCard
              product={product}
              layoutId={`product-card-${gridId}-${product.id}`}
              inCart={cart.some(
                (item) => item.id === product.id && item.size === resolveCartSize(product, userSize)
              )}
              onAddToCart={onAddToCart}
              onOpen={() => setSelectedIndex(i)}
              userSize={userSize}
            />
          </motion.div>
        ))}
      </motion.div>

      {createPortal(
        <AnimatePresence>
          {isOpen && (
            <motion.div
              className="fixed inset-0 z-[60] flex items-center justify-center bg-foreground/50 p-6 backdrop-blur-sm"
              initial={{ opacity: 0 }}
              animate={{ opacity: 1 }}
              exit={{ opacity: 0 }}
              onClick={() => setSelectedIndex(null)}
            >
              <motion.div
                key={selected.id}
                layoutId={`product-card-${gridId}-${selected.id}`}
                className="relative flex w-full max-w-3xl flex-col overflow-hidden rounded-2xl bg-card sm:flex-row"
                drag="x"
                dragConstraints={{ left: 0, right: 0 }}
                dragElastic={0.15}
                dragMomentum={false}
                onDragEnd={(e, info) => {
                  const threshold = 80;
                  if (info.offset.x < -threshold) setSelectedIndex((i) => Math.min(i + 1, products.length - 1));
                  else if (info.offset.x > threshold) setSelectedIndex((i) => Math.max(i - 1, 0));
                }}
                onClick={(e) => e.stopPropagation()}
              >
                <ProductArt product={selected} className="aspect-[4/3] w-full sm:aspect-auto sm:w-1/2" />

                <div className="flex flex-1 flex-col gap-4 p-8">
                  <div>
                    <p className="text-xs tracking-widest text-muted-foreground uppercase">{selected.brand}</p>
                    <h2 className="font-hero mt-1 text-2xl">{selected.name}</h2>
                  </div>

                  {selected.description && (
                    <p className="text-sm leading-relaxed text-muted-foreground">{selected.description}</p>
                  )}

                  {selected.color && (
                    <div className="flex items-center gap-2">
                      <span
                        className="size-3 rounded-full border border-border"
                        style={{ backgroundColor: selected.color.toLowerCase() }}
                      />
                      <span className="text-xs text-muted-foreground">{selected.color}</span>
                    </div>
                  )}

                  {selected.sizes && (
                    <div>
                      <p className="mb-2 text-xs tracking-widest text-muted-foreground uppercase">
                        Select a size
                      </p>
                      <div className="flex flex-wrap items-center gap-2">
                        {SIZE_ORDER.map((size) => {
                          const count = selected.sizes[size] ?? 0;
                          const soldOut = count === 0;
                          return (
                            <button
                              key={size}
                              type="button"
                              disabled={soldOut}
                              onClick={() => setChosenSize(size)}
                              title={soldOut ? `Sold out in ${size}` : `${count} in stock in ${size}`}
                              className={cn(
                                "min-w-11 rounded-lg border px-2.5 py-1.5 text-sm font-medium transition-colors",
                                soldOut &&
                                  "cursor-not-allowed border-transparent text-muted-foreground/40 line-through",
                                !soldOut &&
                                  chosenSize !== size &&
                                  "border-border hover:border-mustard hover:text-foreground",
                                chosenSize === size && "border-primary bg-primary text-primary-foreground"
                              )}
                            >
                              {size}
                            </button>
                          );
                        })}
                      </div>
                      <SizeNote product={selected} userSize={userSize} chosenSize={chosenSize} />
                    </div>
                  )}

                  <span className="text-2xl font-semibold text-foreground">₹{selected.price?.toLocaleString()}</span>

                  <Button
                    size="lg"
                    className="mt-auto gap-2 rounded-lg"
                    disabled={!chosenSize}
                    onClick={() => onAddToCart(selected, chosenSize)}
                  >
                    {cart.some((item) => item.id === selected.id && item.size === chosenSize) ? (
                      <>
                        <Check className="size-4" /> Added in {chosenSize}
                      </>
                    ) : chosenSize ? (
                      <>
                        <Plus className="size-4" /> Add {chosenSize} to Cart
                      </>
                    ) : (
                      "Sold out"
                    )}
                  </Button>
                </div>

                <button
                  onClick={() => setSelectedIndex(null)}
                  className="absolute top-4 right-4 rounded-full bg-background/85 p-2 text-foreground shadow-sm backdrop-blur-sm transition-colors hover:bg-background"
                >
                  <X className="size-4" />
                </button>

                {selectedIndex > 0 && (
                  <button
                    onClick={() => setSelectedIndex((i) => i - 1)}
                    className="absolute top-1/2 left-3 -translate-y-1/2 rounded-full bg-background/85 p-2 text-foreground shadow-sm backdrop-blur-sm transition-colors hover:bg-background"
                  >
                    <ChevronLeft className="size-5" />
                  </button>
                )}
                {selectedIndex < products.length - 1 && (
                  <button
                    onClick={() => setSelectedIndex((i) => i + 1)}
                    className="absolute top-1/2 right-3 -translate-y-1/2 rounded-full bg-background/85 p-2 text-foreground shadow-sm backdrop-blur-sm transition-colors hover:bg-background"
                  >
                    <ChevronRight className="size-5" />
                  </button>
                )}
              </motion.div>
            </motion.div>
          )}
        </AnimatePresence>,
        document.body
      )}
    </>
  );
}
