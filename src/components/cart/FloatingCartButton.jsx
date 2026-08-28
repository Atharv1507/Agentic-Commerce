import { motion } from "framer-motion";
import { ShoppingCart } from "lucide-react";

// Shares layoutId="cart-shell" with CartModal's sheet — mounted/unmounted by the
// same AnimatePresence in App.jsx, so framer-motion morphs this pill into the
// bottom sheet rather than just cross-fading between two unrelated elements.
//
// Anchored to the chat header's top-right rather than floating over the
// conversation: parked above the composer it sat on top of the last thing the
// agent said, which is exactly the message that explains what just went into
// the cart. `top-4` lines it up with the header's own py-4, and the horizontal
// inset matches the header's px-6 / md:px-10.
export default function FloatingCartButton({ count, onClick }) {
  return (
    <motion.button
      layoutId="cart-shell"
      onClick={onClick}
      className="fixed top-4 right-6 z-50 flex items-center justify-center gap-2 rounded-full bg-primary px-4 py-2.5 text-primary-foreground shadow-lg shadow-primary/25 transition-colors hover:bg-sand hover:text-sand-foreground md:right-10"
      initial={{ scale: 0, opacity: 0 }}
      animate={{ scale: 1, opacity: 1 }}
      exit={{ scale: 0, opacity: 0 }}
      whileHover={{ scale: 1.03 }}
      whileTap={{ scale: 0.97 }}
    >
      <ShoppingCart className="size-4" />
      <span className="text-sm font-semibold">View Cart</span>
      <span className="flex size-5 items-center justify-center rounded-full bg-primary-foreground/20 text-xs font-bold">
        {count}
      </span>
    </motion.button>
  );
}
