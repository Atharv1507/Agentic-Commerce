import { motion } from "framer-motion";
import { cn } from "@/lib/utils";

export default function OptionChips({ options, onSelect }) {
  return (
    <motion.div
      className="flex w-full justify-start"
      initial={{ opacity: 0, y: 10 }}
      animate={{ opacity: 1, y: 0 }}
      transition={{ duration: 0.3 }}
    >
      <div className="flex flex-wrap gap-2 max-w-[80%]">
        {options.map((option, i) => (
          <motion.button
            key={option}
            onClick={() => onSelect(option)}
            className={cn(
              "px-4 py-2 rounded-full text-sm font-medium transition-all",
              "border border-border bg-card text-card-foreground",
              "hover:border-primary hover:bg-primary/10"
            )}
            initial={{ opacity: 0, scale: 0.8 }}
            animate={{ opacity: 1, scale: 1 }}
            transition={{ delay: i * 0.05 }}
            whileHover={{ scale: 1.05 }}
            whileTap={{ scale: 0.95 }}
          >
            {option}
          </motion.button>
        ))}
      </div>
    </motion.div>
  );
}
