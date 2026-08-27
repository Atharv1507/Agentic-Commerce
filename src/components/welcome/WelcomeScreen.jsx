import { motion } from "framer-motion";
import { ShoppingBag } from "lucide-react";
import { cn } from "@/lib/utils";

function getGreeting() {
  const hour = new Date().getHours();
  if (hour < 12) return "Good morning";
  if (hour < 17) return "Good afternoon";
  return "Good evening";
}

export default function WelcomeScreen({ name, onContinue }) {
  return (
    <div className="flex min-h-screen items-center justify-center p-8">
      <motion.div
        className="text-center max-w-lg"
        initial={{ opacity: 0, y: 30 }}
        animate={{ opacity: 1, y: 0 }}
        transition={{ duration: 0.8, ease: "easeOut" }}
      >
        <motion.div
          initial={{ scale: 0 }}
          animate={{ scale: 1 }}
          transition={{ delay: 0.3, type: "spring", stiffness: 200 }}
          className="mb-8 inline-flex items-center justify-center size-20 rounded-full bg-primary/10"
        >
          <ShoppingBag className="size-10 text-primary" />
        </motion.div>

        <motion.h1
          className="font-heading text-4xl md:text-5xl font-semibold mb-4"
          initial={{ opacity: 0, y: 10 }}
          animate={{ opacity: 1, y: 0 }}
          transition={{ delay: 0.5 }}
        >
          {getGreeting()}, {name}
        </motion.h1>

        <motion.p
          className="text-muted-foreground text-lg mb-10"
          initial={{ opacity: 0 }}
          animate={{ opacity: 1 }}
          transition={{ delay: 0.7 }}
        >
          How can I assist you today?
        </motion.p>

        <motion.button
          onClick={onContinue}
          className={cn(
            "px-8 py-4 rounded-xl font-semibold text-lg",
            "bg-primary text-primary-foreground",
            "hover:bg-accent transition-colors"
          )}
          initial={{ opacity: 0, y: 10 }}
          animate={{ opacity: 1, y: 0 }}
          transition={{ delay: 0.9 }}
          whileHover={{ scale: 1.03 }}
          whileTap={{ scale: 0.97 }}
        >
          Start Shopping
        </motion.button>
      </motion.div>
    </div>
  );
}
