import { useState } from "react";
import { motion, AnimatePresence } from "framer-motion";
import {
  PanelLeftClose,
  PanelLeftOpen,
  House,
  SquarePen,
  MessageCircle,
  Settings,
  Plus,
  Check,
  Trash2,
} from "lucide-react";
import { cn, DEFAULT_ASSISTANT_NAME, getAssistantInitials } from "@/lib/utils";
import { ProductArt } from "@/components/products/ProductCard";

// Nested buttons aren't valid HTML, so the row is a div with the label as the
// button — that keeps the delete control a real sibling button rather than
// something that has to stopPropagation its way out of a parent button.
function ThreadRow({ thread, onClick, onDelete }) {
  const [confirming, setConfirming] = useState(false);

  return (
    <div
      className={cn(
        "group flex w-full items-center gap-1 rounded-xl pr-1.5 transition-colors",
        thread.isActive ? "bg-primary/10 text-foreground" : "text-muted-foreground hover:bg-secondary/60 hover:text-foreground"
      )}
      onMouseLeave={() => setConfirming(false)}
    >
      <button onClick={onClick} className="flex min-w-0 flex-1 items-start gap-2.5 px-3 py-2.5 text-left">
        <MessageCircle
          className={cn("mt-0.5 size-4 shrink-0", thread.isActive ? "text-primary" : "text-muted-foreground/60")}
        />
        <span className="min-w-0 flex-1 truncate text-sm leading-snug">{thread.title}</span>
      </button>

      {/* Two-step: the first click arms it, the second deletes. Cheaper than a
          modal for something this small, and still not a one-click mistake. */}
      <button
        onClick={() => (confirming ? onDelete() : setConfirming(true))}
        className={cn(
          "shrink-0 rounded-lg p-1.5 transition-all focus-visible:opacity-100",
          confirming
            ? "bg-destructive/15 text-destructive opacity-100"
            : "text-muted-foreground/60 opacity-0 hover:text-foreground group-hover:opacity-100"
        )}
        aria-label={confirming ? `Confirm delete "${thread.title}"` : `Delete "${thread.title}"`}
        title={confirming ? "Click again to delete" : "Delete chat"}
      >
        {confirming ? <Check className="size-3.5" /> : <Trash2 className="size-3.5" />}
      </button>
    </div>
  );
}

function SeenProductRow({ product, inCart, onAddToCart }) {
  return (
    <div className="group flex items-center gap-2.5 rounded-xl px-3 py-2 transition-colors hover:bg-secondary/60">
      <ProductArt product={product} className="size-9 shrink-0 rounded-lg" />
      <div className="min-w-0 flex-1">
        <p className="truncate text-sm leading-tight">{product.name}</p>
        <p className="truncate text-xs text-muted-foreground">₹{product.price?.toLocaleString()}</p>
      </div>
      <button
        onClick={() => onAddToCart(product)}
        className={cn(
          "shrink-0 rounded-lg p-1.5 opacity-0 transition-opacity group-hover:opacity-100",
          inCart ? "bg-primary/20 text-primary opacity-100" : "bg-primary text-primary-foreground"
        )}
        aria-label={inCart ? "Remove from cart" : "Add to cart"}
      >
        {inCart ? <Check className="size-3.5" /> : <Plus className="size-3.5" />}
      </button>
    </div>
  );
}

export default function ChatSidebar({
  threads,
  seenProducts,
  cart,
  assistantName,
  onSelectThread,
  onNewChat,
  onDeleteThread,
  onGoHome,
  onOpenSettings,
  onAddToCart,
}) {
  const [collapsed, setCollapsed] = useState(false);
  const displayName = assistantName || DEFAULT_ASSISTANT_NAME;

  return (
    <motion.aside
      animate={{ width: collapsed ? 72 : 280 }}
      transition={{ type: "spring", stiffness: 300, damping: 30 }}
      className="relative z-10 flex h-screen shrink-0 flex-col border-r border-border bg-card/40 backdrop-blur-sm"
    >
      <div className={cn("flex items-center gap-2 border-b border-border p-3", collapsed && "flex-col")}>
        <div className="flex size-9 shrink-0 items-center justify-center rounded-full bg-primary/20">
          <span className="text-sm font-semibold text-primary">{getAssistantInitials(displayName)}</span>
        </div>
        {!collapsed && <span className="font-hero flex-1 truncate text-sm">{displayName}</span>}
        <button
          onClick={() => setCollapsed((c) => !c)}
          className="shrink-0 rounded-lg p-1.5 text-muted-foreground transition-colors hover:bg-secondary hover:text-foreground"
          aria-label={collapsed ? "Expand sidebar" : "Collapse sidebar"}
        >
          {collapsed ? <PanelLeftOpen className="size-4" /> : <PanelLeftClose className="size-4" />}
        </button>
      </div>

      <div className={cn("flex flex-col gap-1.5 p-3", collapsed && "items-center")}>
        <button
          onClick={onGoHome}
          className={cn(
            "flex items-center gap-2.5 rounded-xl px-3 py-2 text-sm text-muted-foreground transition-colors hover:bg-secondary/60 hover:text-foreground",
            collapsed && "w-auto justify-center px-2.5"
          )}
        >
          <House className="size-4 shrink-0" />
          {!collapsed && "Home"}
        </button>
        <button
          onClick={onNewChat}
          className={cn(
            "flex items-center gap-2.5 rounded-xl px-3 py-2 text-sm text-muted-foreground transition-colors hover:bg-secondary/60 hover:text-foreground",
            collapsed && "w-auto justify-center px-2.5"
          )}
        >
          <SquarePen className="size-4 shrink-0" />
          {!collapsed && "New chat"}
        </button>
      </div>

      <AnimatePresence>
        {!collapsed && (
          <motion.div
            initial={{ opacity: 0 }}
            animate={{ opacity: 1 }}
            exit={{ opacity: 0 }}
            className="flex flex-1 flex-col gap-4 overflow-y-auto px-3 pb-3"
          >
            <div className="flex flex-col gap-1">
              <p className="px-3 py-1 text-xs tracking-widest text-muted-foreground/70 uppercase">Chats</p>
              {threads.map((thread) => (
                <ThreadRow
                  key={thread.id}
                  thread={thread}
                  onClick={() => onSelectThread(thread.id)}
                  onDelete={() => onDeleteThread(thread.id)}
                />
              ))}
            </div>

            {seenProducts.length > 0 && (
              <div className="flex flex-col gap-1">
                <p className="px-3 py-1 text-xs tracking-widest text-muted-foreground/70 uppercase">
                  Seen in this chat
                </p>
                {seenProducts.map((product) => (
                  <SeenProductRow
                    key={product.id}
                    product={product}
                    inCart={cart.some((item) => item.id === product.id)}
                    onAddToCart={onAddToCart}
                  />
                ))}
              </div>
            )}
          </motion.div>
        )}
      </AnimatePresence>

      <div className={cn("mt-auto border-t border-border p-3", collapsed && "flex justify-center")}>
        <button
          onClick={onOpenSettings}
          className={cn(
            "flex items-center gap-2.5 rounded-xl px-3 py-2 text-sm text-muted-foreground transition-colors hover:bg-secondary/60 hover:text-foreground",
            collapsed && "w-auto justify-center px-2.5"
          )}
        >
          <Settings className="size-4 shrink-0" />
          {!collapsed && "Preferences"}
        </button>
      </div>
    </motion.aside>
  );
}
