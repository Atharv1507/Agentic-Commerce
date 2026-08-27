import { useEffect, useRef } from "react";
import { motion } from "framer-motion";
import ChatMessage from "./ChatMessage";
import ChatInput from "./ChatInput";
import OptionChips from "./OptionChips";
import TypingIndicator from "./TypingIndicator";

export default function ChatWindow({ messages, isTyping, onSend, onOptionSelect }) {
  const scrollRef = useRef(null);

  useEffect(() => {
    if (scrollRef.current) {
      scrollRef.current.scrollTop = scrollRef.current.scrollHeight;
    }
  }, [messages, isTyping]);

  return (
    <div className="flex flex-col h-screen bg-background">
      {/* Header */}
      <motion.div
        className="flex items-center gap-3 px-6 py-4 border-b border-border bg-background/80 backdrop-blur-sm"
        initial={{ opacity: 0, y: -10 }}
        animate={{ opacity: 1, y: 0 }}
      >
        <div className="size-9 rounded-full bg-primary/20 flex items-center justify-center">
          <span className="text-primary font-semibold text-sm">SA</span>
        </div>
        <div>
          <h2 className="font-heading text-base font-semibold">Shopper Agent</h2>
          <p className="text-xs text-muted-foreground">Always here to help</p>
        </div>
      </motion.div>

      {/* Messages */}
      <div
        ref={scrollRef}
        className="flex-1 overflow-y-auto px-6 py-6 flex flex-col gap-4"
      >
        {messages.map((msg) => {
          if (msg.type === "options") {
            return (
              <div key={msg.id}>
                <ChatMessage message={{ role: "agent", content: msg.content }} />
                <div className="mt-2">
                  <OptionChips options={msg.options} onSelect={onOptionSelect} />
                </div>
              </div>
            );
          }
          return <ChatMessage key={msg.id} message={msg} />;
        })}
        {isTyping && <TypingIndicator />}
      </div>

      {/* Input */}
      <ChatInput onSend={onSend} disabled={isTyping} />
    </div>
  );
}
