import { useState } from "react";
import { motion } from "framer-motion";
import { Send } from "lucide-react";
import { Input } from "@/components/ui/input";
import { Button } from "@/components/ui/button";

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
    <div className="relative z-10 flex items-center gap-3 border-t border-border bg-background/80 p-4 backdrop-blur-sm md:px-10 md:py-5">
      <Input
        value={value}
        onChange={(e) => setValue(e.target.value)}
        onKeyDown={handleKeyDown}
        disabled={disabled}
        placeholder="Type a message..."
        className="h-12 flex-1 rounded-xl border-border bg-card px-5 text-base focus-visible:ring-primary/40"
      />
      <motion.div whileHover={value.trim() ? { scale: 1.05 } : {}} whileTap={value.trim() ? { scale: 0.95 } : {}}>
        <Button
          onClick={handleSend}
          disabled={!value.trim() || disabled}
          size="icon-lg"
          className="rounded-xl"
        >
          <Send className="size-5" />
        </Button>
      </motion.div>
    </div>
  );
}
