import { motion } from "framer-motion";
import { cn } from "@/lib/utils";

export default function ChatMessage({ message }) {
  const isAgent = message.role === "agent";

  return (
    <motion.div
      className={cn("flex w-full", isAgent ? "justify-start" : "justify-end")}
      initial={{ opacity: 0, y: 10 }}
      animate={{ opacity: 1, y: 0 }}
      transition={{ duration: 0.3 }}
    >
      <div
        className={cn(
          "max-w-[80%] px-5 py-3 rounded-2xl text-[15px] leading-relaxed",
          isAgent
            ? "bg-card text-card-foreground rounded-bl-md"
            : "bg-primary text-primary-foreground rounded-br-md"
        )}
      >
        {message.content}
      </div>
    </motion.div>
  );
}
