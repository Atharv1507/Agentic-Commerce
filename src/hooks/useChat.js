import { useState, useCallback, useMemo } from "react";
import { DEFAULT_ASSISTANT_NAME } from "@/lib/utils";

const API_BASE = import.meta.env.VITE_API_BASE_URL || "http://localhost:8000";
const API_URL = `${API_BASE}/chat`;
const STREAM_URL = `${API_BASE}/chat/stream`;

// How each clarifying-form facet reads back to the agent as plain language.
const FACET_LABELS = {
  colors: "Colour",
  brands: "Brand",
  materials: "Fabric",
  price_bands: "Budget",
};

// A turn can take several rounds of back-and-forth with the seller agent, so
// the backend narrates what it's actually doing over SSE. Read the stream,
// surface every progress label, and keep the final event as the result.
// Falls back to the plain /chat endpoint if streaming isn't available.
async function streamChat(body, onProgress) {
  const res = await fetch(STREAM_URL, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  });

  if (!res.ok || !res.body) throw new Error(`stream unavailable (${res.status})`);

  const reader = res.body.getReader();
  const decoder = new TextDecoder();
  let buffer = "";
  let final = null;

  for (;;) {
    const { done, value } = await reader.read();
    if (done) break;
    buffer += decoder.decode(value, { stream: true });

    // SSE frames are separated by a blank line; a partial frame stays buffered.
    const frames = buffer.split("\n\n");
    buffer = frames.pop() ?? "";

    for (const frame of frames) {
      const line = frame.split("\n").find((l) => l.startsWith("data:"));
      if (!line) continue;
      let event;
      try {
        event = JSON.parse(line.slice(5).trim());
      } catch {
        continue;
      }
      if (event.type === "final") final = event;
      else if (event.type === "progress") onProgress(event);
    }
  }

  if (!final) throw new Error("stream ended without a final event");
  return final;
}

function greetingMessage(name, assistantName) {
  return {
    id: "greeting",
    role: "agent",
    content: `Hey ${name || "there"}! I'm ${assistantName || DEFAULT_ASSISTANT_NAME}, your shopping assistant. What can I help you find today?`,
  };
}

export default function useChat(session, { initialMessages, initialCart, onProfileSynced } = {}) {
  // Raw state keeps the greeting placeholder-only; the name gets interpolated
  // in the `messages` memo below so it always reflects the live session,
  // instead of patching stored state via an effect when the name arrives late.
  const [rawMessages, setRawMessages] = useState(
    () => initialMessages || [{ id: "greeting", role: "agent", isGreeting: true }]
  );
  const [isTyping, setIsTyping] = useState(false);
  // Latest progress event from the backend's SSE narration, or null when the
  // agent isn't mid-turn.
  const [progress, setProgress] = useState(null);
  const [cart, setCart] = useState(() => initialCart || []);
  // Which conversation this chat is showing. Sent with every message so the
  // backend keeps one memory per chat: switching back to an older chat restores
  // its context, and nothing said here reaches a different chat.
  const [threadId, setThreadId] = useState(null);

  const messages = useMemo(
    () =>
      rawMessages.map((m) =>
        m.isGreeting ? { ...m, content: greetingMessage(session?.name, session?.assistantName).content } : m
      ),
    [rawMessages, session?.name, session?.assistantName]
  );

  const addMessage = useCallback((msg) => {
    setRawMessages((prev) => [...prev, { ...msg, id: Date.now() + Math.random() }]);
  }, []);

  // Swap the entire conversation + cart for a different thread (sidebar/landing
  // history switch) without recreating the hook — resets in place.
  const restoreThread = useCallback((thread) => {
    setRawMessages(thread?.messages?.length ? thread.messages : [{ id: "greeting", role: "agent", isGreeting: true }]);
    setCart(thread?.cart || []);
    setThreadId(thread?.id || null);
    setIsTyping(false);
    setProgress(null);
  }, []);

  const openRazorpay = useCallback(
    (order, onPaymentComplete) => {
      if (!window.Razorpay) {
        addMessage({ role: "agent", content: "Payment couldn't start — the checkout script didn't load." });
        return;
      }
      const rzp = new window.Razorpay({
        key: import.meta.env.VITE_RAZORPAY_KEY_ID,
        order_id: order.order_id,
        amount: order.amount,
        currency: order.currency || "INR",
        name: session?.assistantName || DEFAULT_ASSISTANT_NAME,
        description: `Order for ${order.product_ids?.length || 0} item(s)`,
        prefill: {
          name: order.buyer?.name || "",
          email: order.buyer?.email || "",
          contact: order.buyer?.phone || "",
        },
        theme: { color: "#6c584c" },
        handler: (paymentResponse) => {
          onPaymentComplete(paymentResponse.razorpay_payment_id, order.order_id);
        },
        modal: {
          ondismiss: () => {
            addMessage({ role: "agent", content: "Payment window closed. Your order is still waiting — checkout again whenever you're ready." });
          },
        },
      });
      rzp.open();
    },
    [addMessage, session]
  );

  const sendMessage = useCallback(
    async (text, { displayText } = {}) => {
      addMessage({ role: "user", content: displayText ?? text });
      setIsTyping(true);
      setProgress(null);

      try {
        const body = { email: session.email, text, thread_id: threadId || "default" };
        let data;
        try {
          data = await streamChat(body, (event) => setProgress(event));
        } catch {
          // Streaming unavailable — fall back to the blocking endpoint so the
          // conversation still works, just without the narration.
          setProgress(null);
          const res = await fetch(API_URL, {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify(body),
          });
          data = await res.json();
        }

        const response = data.response || "Sorry, something went wrong.";

        // Details the agent collected mid-chat (typically the address given at
        // checkout) come back on the turn that saved them, so Settings shows
        // them without the shopper entering anything twice.
        if (data.profile && onProfileSynced) {
          onProfileSynced(data.profile);
        }

        const checkoutResult = data.tool_results?.find((tr) => tr.tool === "checkout_cart")?.result;
        if (checkoutResult?.order_id) {
          setCart([]);
        }

        if (data.form?.fields?.length) {
          // Clarifying form — rendered inline as a skippable card. No product
          // results accompany it; the search runs once the user responds.
          addMessage({ role: "agent", content: response, type: "form", form: data.form });
        } else if (Array.isArray(data.products) && data.products.length > 0) {
          addMessage({ role: "agent", content: response, type: "products", products: data.products });
        } else if (Array.isArray(data.options) && data.options.length > 0) {
          addMessage({ role: "agent", content: response, type: "options", options: data.options });
        } else {
          addMessage({ role: "agent", content: response });
        }

        // Cross-sell lands in its own message so it reads as a suggestion
        // rather than as part of what the user actually asked for.
        if (Array.isArray(data.complements) && data.complements.length > 0) {
          addMessage({
            role: "agent",
            type: "products",
            heading: "Goes well with",
            products: data.complements,
          });
        }

        if (checkoutResult?.order_id) {
          // Passed as a call-time argument (not closed over by openRazorpay)
          // so it always resolves to the current sendMessage, including its
          // own recursive self-reference once the SDK's handler fires later.
          openRazorpay(checkoutResult, (paymentId, orderId) => {
            sendMessage(`I've completed the payment (payment_id: ${paymentId}) for order ${orderId}. Please verify it.`);
          });
        }
      } catch {
        addMessage({
          role: "agent",
          content: "I'm having trouble connecting. Please try again.",
        });
      }

      setIsTyping(false);
      setProgress(null);
    },
    [session, threadId, addMessage, openRazorpay, onProfileSynced]
  );

  const selectOption = useCallback((option) => sendMessage(option), [sendMessage]);

  // Turn the clarifying form's chips back into a normal user message. Going
  // through the chat rather than a side channel keeps the agent's history
  // honest — it can see exactly what the shopper chose and what they skipped.
  const answerPreferences = useCallback(
    (messageId, answers) => {
      setRawMessages((prev) => prev.map((m) => (m.id === messageId ? { ...m, answered: true } : m)));

      const parts = Object.entries(answers)
        .filter(([, values]) => values?.length)
        .map(([key, values]) => `${FACET_LABELS[key] || key}: ${values.join(", ")}`);

      sendMessage(
        parts.length
          ? `${parts.join("; ")}. Skip anything I didn't mention.`
          : "No particular preferences — just show me what you have."
      );
    },
    [sendMessage]
  );

  const skipPreferences = useCallback(
    (messageId) => {
      setRawMessages((prev) =>
        prev.map((m) => (m.id === messageId ? { ...m, answered: true, skipped: true } : m))
      );
      sendMessage("No particular preferences — just show me what you have.");
    },
    [sendMessage]
  );

  const addToCart = useCallback(
    (product) => {
      setCart((prev) => {
        const exists = prev.some((p) => p.id === product.id);
        if (exists) {
          fetch(`${API_BASE}/cart/${session.email}/${product.id}`, { method: "DELETE" }).catch(() => {});
          return prev.filter((p) => p.id !== product.id);
        }
        fetch(`${API_BASE}/cart/${session.email}`, {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify(product),
        }).catch(() => {});
        return [...prev, product];
      });
    },
    [session]
  );

  const removeFromCart = useCallback(
    (productId) => {
      setCart((prev) => prev.filter((p) => p.id !== productId));
      fetch(`${API_BASE}/cart/${session.email}/${productId}`, { method: "DELETE" }).catch(() => {});
    },
    [session]
  );

  const confirmOrder = useCallback(async () => {
    if (cart.length === 0) return;
    const total = cart.reduce((sum, item) => sum + (item.price || 0) * (item.quantity || 1), 0);
    await sendMessage("Please check out my cart now.", {
      displayText: `Checkout ${cart.length} item(s) — ₹${total.toLocaleString()}`,
    });
  }, [cart, sendMessage]);

  return {
    messages,
    isTyping,
    progress,
    cart,
    threadId,
    sendMessage,
    selectOption,
    answerPreferences,
    skipPreferences,
    addToCart,
    removeFromCart,
    confirmOrder,
    restoreThread,
  };
}
