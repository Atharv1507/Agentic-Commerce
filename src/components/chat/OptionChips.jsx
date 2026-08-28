import { motion } from "framer-motion";
import { Button } from "@/components/ui/button";

export default function OptionChips({ options, onSelect }) {
  return (
    <motion.div
      className="flex w-full justify-start"
      initial={{ opacity: 0, y: 10 }}
      animate={{ opacity: 1, y: 0 }}
      transition={{ duration: 0.3 }}
    >
      <div className="flex max-w-[80%] flex-wrap gap-2">
        {options.map((option, i) => (
          <motion.div
            key={option}
            initial={{ opacity: 0, scale: 0.8 }}
            animate={{ opacity: 1, scale: 1 }}
            transition={{ delay: i * 0.05 }}
            whileHover={{ scale: 1.05 }}
            whileTap={{ scale: 0.95 }}
          >
            <Button
              variant="outline"
              size="sm"
              onClick={() => onSelect(option)}
              className="rounded-full border-border bg-card text-sm font-medium hover:border-primary hover:bg-primary/10"
            >
              {option}
            </Button>
          </motion.div>
        ))}
      </div>
    </motion.div>
  );
}
