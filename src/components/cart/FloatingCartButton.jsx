import { motion } from "framer-motion";
import { ShoppingCart } from "lucide-react";

// Shares layoutId="cart-shell" with CartModal's sheet — mounted/unmounted by the
// same AnimatePresence in App.jsx, so framer-motion morphs this pill into the
// bottom sheet rather than just cross-fading between two unrelated elements.
export default function FloatingCartButton({ count, onClick }) {
  return (
    <motion.button
      layoutId="cart-shell"
      onClick={onClick}
      className="fixed inset-x-0 bottom-28 z-50 mx-auto flex w-fit max-w-[60vw] items-center justify-center gap-2 rounded-full bg-primary px-5 py-3.5 text-primary-foreground shadow-lg shadow-primary/25 transition-colors hover:bg-accent"
      initial={{ scale: 0, opacity: 0 }}
      animate={{ scale: 1, opacity: 1 }}
      exit={{ scale: 0, opacity: 0 }}
      whileHover={{ scale: 1.03 }}
      whileTap={{ scale: 0.97 }}
    >
      <ShoppingCart className="size-5" />
      <span className="text-sm font-semibold">View Cart</span>
      <span className="flex size-5 items-center justify-center rounded-full bg-primary-foreground/20 text-xs font-bold">
        {count}
      </span>
    </motion.button>
  );
}
