import { motion } from "framer-motion";
import { BadgePercent } from "lucide-react";
import ChatMessage from "./ChatMessage";
import ChatInput from "./ChatInput";
import OptionChips from "./OptionChips";
import PreferenceModal from "./PreferenceModal";
import TypingIndicator from "./TypingIndicator";
import ProductGrid from "@/components/products/ProductGrid";
import {
  MessageScrollerProvider,
  MessageScroller,
  MessageScrollerViewport,
  MessageScrollerContent,
  MessageScrollerItem,
  MessageScrollerButton,
} from "@/components/ui/message-scroller";
import { DEFAULT_ASSISTANT_NAME, DEFAULT_ASSISTANT_AVATAR } from "@/lib/utils";

export default function ChatWindow({
  messages,
  isTyping,
  progress,
  onSend,
  onOptionSelect,
  onAnswerPreferences,
  onSkipPreferences,
  cart,
  onAddToCart,
  assistantName,
  userSize,
  threadId,
}) {
  const displayName = assistantName || DEFAULT_ASSISTANT_NAME;

  return (
    <div className="relative flex min-h-0 min-w-0 flex-1 flex-col overflow-hidden bg-background">
      {/* Ambient glow — keeps the shader's warmth alive behind the chat instead of a flat wall of linen */}
      <div className="pointer-events-none absolute inset-0 z-0 overflow-hidden">
        <div className="ambient-glow absolute -top-32 -right-24 size-96 rounded-full bg-mustard/25 blur-3xl" />
        <div
          className="ambient-glow absolute -bottom-40 -left-20 size-96 rounded-full bg-sand/25 blur-3xl"
          style={{ animationDelay: "-7s" }}
        />
      </div>

      {/* Header */}
      <motion.div
        className="relative z-10 flex items-center gap-3 border-b border-border bg-background/80 px-6 py-4 backdrop-blur-sm md:px-10"
        initial={{ opacity: 0, y: -10 }}
        animate={{ opacity: 1, y: 0 }}
      >
        <div className="relative flex size-9 items-center justify-center overflow-hidden rounded-full bg-mustard/20">
          <span
            className="absolute inset-0 rounded-full bg-mustard/40 blur-md"
            style={{ animation: "ambient-drift 3.2s ease-in-out infinite" }}
          />
          <img src={DEFAULT_ASSISTANT_AVATAR} alt={displayName} className="relative size-full object-cover" />
        </div>
        <div>
          <h2 className="text-lg font-semibold">{displayName}</h2>
          <p className="flex items-center gap-1.5 text-xs tracking-wide text-muted-foreground uppercase">
            <span className="size-1.5 rounded-full bg-primary shadow-[0_0_6px_var(--color-primary)]" />
            Always here to help
          </p>
        </div>
      </motion.div>

      {/* Messages */}
      {/* Scrolling follows the shopper's OWN messages, not the bottom of the
          transcript: each user turn is a scroll anchor, so sending one pulls it
          to the top of the viewport and the reply lands underneath, read from
          its first line. Sticking to the bottom instead would leave a reply
          that contains a product grid showing nothing but the last row of
          cards, with the agent's actual answer scrolled off the top — the
          taller the reply, the worse the result.

          `last-anchor` seeds the same view when a conversation is opened or
          restored: the newest exchange, from the question that started it,
          falling back to the very end when what follows already fits.

          Keyed on the thread so switching chats re-seeds it. Without the key
          the provider never unmounts, its "default position already applied"
          latch stays set, and an older conversation opens at whatever scroll
          offset the previous one happened to be left at.

          The scroll-to-end button below stays available throughout, so jumping
          to the absolute bottom is always one tap away. */}
      <MessageScrollerProvider key={threadId || "new"} autoScroll defaultScrollPosition="last-anchor">
        <MessageScroller className="relative z-10 flex-1">
          <MessageScrollerViewport>
            <MessageScrollerContent className="px-6 py-8 md:px-10">
              {messages.map((msg) => (
                <MessageScrollerItem
                  key={msg.id}
                  messageId={msg.id}
                  scrollAnchor={msg.role === "user"}
                >
                  {msg.type === "form" ? (
                    <div className="flex flex-col gap-3">
                      {msg.content && <ChatMessage message={{ role: "agent", content: msg.content }} />}
                      {msg.answered ? (
                        <p className="px-4 text-xs text-muted-foreground/70">
                          {msg.skipped ? "Skipped." : "Preferences applied."}
                        </p>
                      ) : (
                        <PreferenceModal
                          form={msg.form}
                          onSubmit={(answers) => onAnswerPreferences(msg.id, answers)}
                          onSkipAll={() => onSkipPreferences(msg.id)}
                        />
                      )}
                    </div>
                  ) : msg.type === "options" ? (
                    <div className="flex flex-col gap-2">
                      <ChatMessage message={{ role: "agent", content: msg.content }} />
                      <OptionChips options={msg.options} onSelect={onOptionSelect} />
                    </div>
                  ) : msg.type === "offers" ? (
                    <div className="flex flex-col gap-2 px-4">
                      {/* Rendered as the shop's own voice, distinct from the
                          agent's bubbles: it's the merchant's promise, and it
                          shouldn't read as the assistant inventing a deal. */}
                      <p className="text-xs tracking-widest text-muted-foreground/70 uppercase">
                        Offer from the shop
                      </p>
                      {msg.offers.map((offer) => (
                        <div
                          key={offer.id}
                          className="flex items-start gap-2.5 rounded-2xl border border-border bg-card px-4 py-3"
                        >
                          <BadgePercent className="mt-0.5 size-4 shrink-0 text-sand" />
                          <p className="text-sm text-foreground">{offer.description}</p>
                        </div>
                      ))}
                    </div>
                  ) : msg.type === "products" ? (
                    <div className="flex flex-col gap-3">
                      {msg.content && <ChatMessage message={{ role: "agent", content: msg.content }} />}
                      {msg.heading && (
                        <p className="px-4 text-xs tracking-widest text-muted-foreground/70 uppercase">
                          {msg.heading}
                        </p>
                      )}
                      <ProductGrid
                        products={msg.products}
                        cart={cart}
                        onAddToCart={onAddToCart}
                        gridId={String(msg.id)}
                        userSize={userSize}
                      />
                    </div>
                  ) : (
                    <ChatMessage message={msg} />
                  )}
                </MessageScrollerItem>
              ))}
              {isTyping && (
                <MessageScrollerItem messageId="typing" className="shrink-0">
                  <TypingIndicator progress={progress} />
                </MessageScrollerItem>
              )}
            </MessageScrollerContent>
          </MessageScrollerViewport>
          <MessageScrollerButton />
        </MessageScroller>
      </MessageScrollerProvider>

      {/* Input */}
      <ChatInput onSend={onSend} disabled={isTyping} />
    </div>
  );
}
