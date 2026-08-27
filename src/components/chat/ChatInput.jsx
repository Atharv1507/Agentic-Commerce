import { useState } from "react";
import { motion } from "framer-motion";
import { Send } from "lucide-react";
import { cn } from "@/lib/utils";

export default function ChatInput({ onSend, disabled }) {
  const [value, setValue] = useState("");

  const handleSend = () => {
    if (value.trim() && !disabled) {
      onSend(value.trim());
      setValue("");
    }
  };

  const handleKeyDown = (e) => {
    if (e.key === "Enter" && !e.shiftKey) {
      e.preventDefault();
      handleSend();
    }
  };

  return (
    <div className="flex items-center gap-3 p-4 border-t border-border bg-background/80 backdrop-blur-sm">
      <input
        value={value}
        onChange={(e) => setValue(e.target.value)}
        onKeyDown={handleKeyDown}
        disabled={disabled}
        placeholder="Type a message..."
        className={cn(
          "flex-1 bg-card border border-border rounded-xl px-5 py-3",
          "focus:outline-none focus:border-primary transition-colors",
          "placeholder:text-muted-foreground text-[15px]",
          "disabled:opacity-50"
        )}
      />
      <motion.button
        onClick={handleSend}
        disabled={!value.trim() || disabled}
        className={cn(
          "p-3 rounded-xl transition-colors",
          value.trim() && !disabled
            ? "bg-primary text-primary-foreground hover:bg-accent"
            : "bg-muted text-muted-foreground cursor-not-allowed"
        )}
        whileHover={value.trim() ? { scale: 1.05 } : {}}
        whileTap={value.trim() ? { scale: 0.95 } : {}}
      >
        <Send className="h-5 w-5" />
      </motion.button>
    </div>
  );
}
