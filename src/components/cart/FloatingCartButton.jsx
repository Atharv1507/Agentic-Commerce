import { motion, AnimatePresence } from "framer-motion";
import { ShoppingCart } from "lucide-react";
import { cn } from "@/lib/utils";

export default function FloatingCartButton({ count, onClick }) {
  return (
    <AnimatePresence>
      {count > 0 && (
        <motion.button
          onClick={onClick}
          className={cn(
            "fixed bottom-6 right-6 z-50",
            "p-4 rounded-full bg-primary text-primary-foreground",
            "shadow-lg shadow-primary/25 hover:bg-accent transition-colors"
          )}
          initial={{ scale: 0, opacity: 0 }}
          animate={{ scale: 1, opacity: 1 }}
          exit={{ scale: 0, opacity: 0 }}
          whileHover={{ scale: 1.1 }}
          whileTap={{ scale: 0.9 }}
        >
          <ShoppingCart className="h-6 w-6" />
          <motion.span
            className="absolute -top-1 -right-1 size-5 rounded-full bg-destructive text-white text-xs font-bold flex items-center justify-center"
            initial={{ scale: 0 }}
            animate={{ scale: 1 }}
            key={count}
          >
            {count}
          </motion.span>
        </motion.button>
      )}
    </AnimatePresence>
  );
}
