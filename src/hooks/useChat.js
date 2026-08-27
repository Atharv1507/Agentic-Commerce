import { useState, useCallback } from "react";

const API_URL = "http://localhost:8000/chat";

export default function useChat(session) {
  const [messages, setMessages] = useState([
    {
      id: "greeting",
      role: "agent",
      content: `Hey ${session?.name || "there"}! I'm your shopping assistant. What can I help you find today?`,
    },
  ]);
  const [isTyping, setIsTyping] = useState(false);
  const [cart, setCart] = useState([]);

  const addMessage = useCallback((msg) => {
    setMessages((prev) => [...prev, { ...msg, id: Date.now() + Math.random() }]);
  }, []);

  const sendMessage = useCallback(
    async (text) => {
      addMessage({ role: "user", content: text });
      setIsTyping(true);

      try {
        const res = await fetch(API_URL, {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ email: session.email, text }),
        });

        const data = await res.json();
        const response = data.response || "Sorry, something went wrong.";

        // Parse response for products
        const productMatch = response.match(/Product ID:\s*(prod_\d+)/g);
        if (productMatch && productMatch.length > 0) {
          // Extract product info from response
          const products = parseProducts(response);
          if (products.length > 0) {
            addMessage({ role: "agent", content: "Here are some options:" });
            addMessage({ role: "agent", content: response, type: "products", products });
            setIsTyping(false);
            return;
          }
        }

        // Check for options/chips
        const optionMatch = response.match(
          /options?.*?:\s*\n((?:-\s*.+\n?)+)/i
        );
        if (optionMatch) {
          const options = optionMatch[1]
            .split("\n")
            .map((l) => l.replace(/^-\s*/, "").trim())
            .filter(Boolean);
          if (options.length > 0 && options.length <= 7) {
            addMessage({
              role: "agent",
              content: response.split(optionMatch[0])[0] || "Choose one:",
              type: "options",
              options,
            });
            setIsTyping(false);
            return;
          }
        }

        addMessage({ role: "agent", content: response });
      } catch (e) {
        addMessage({
          role: "agent",
          content: "I'm having trouble connecting. Please try again.",
        });
      }

      setIsTyping(false);
    },
    [session, addMessage]
  );

  const selectOption = useCallback(
    (option) => {
      sendMessage(option);
    },
    [sendMessage]
  );

  const addToCart = useCallback((product) => {
    setCart((prev) => {
      if (prev.some((p) => p.id === product.id)) {
        return prev.filter((p) => p.id !== product.id);
      }
      return [...prev, product];
    });
  }, []);

  const removeFromCart = useCallback((productId) => {
    setCart((prev) => prev.filter((p) => p.id !== productId));
  }, []);

  const confirmOrder = useCallback(async () => {
    if (cart.length === 0) return;

    const total = cart.reduce((sum, item) => sum + (item.price || 0), 0);
    const productIds = cart.map((p) => p.id);

    setIsTyping(true);
    addMessage({
      role: "user",
      content: `Confirm order for ${cart.length} item(s) — ₹${total.toLocaleString()}`,
    });

    try {
      const res = await fetch(API_URL, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          email: session.email,
          text: `Place the order for product IDs: ${productIds.join(", ")}. Total: ${total}. Use my registered details.`,
        }),
      });

      const data = await res.json();
      addMessage({ role: "agent", content: data.response || "Order placed!" });
      setCart([]);
    } catch (e) {
      addMessage({
        role: "agent",
        content: "Failed to place order. Please try again.",
      });
    }

    setIsTyping(false);
  }, [cart, session, addMessage]);

  return {
    messages,
    isTyping,
    cart,
    sendMessage,
    selectOption,
    addToCart,
    removeFromCart,
    confirmOrder,
  };
}

function parseProducts(text) {
  const products = [];
  const blocks = text.split(/\d+\.\s*\*\*/);

  for (const block of blocks) {
    const nameMatch = block.match(/^(.+?)\*\*/);
    const brandMatch = block.match(/Brand:\s*(.+)/i);
    const priceMatch = block.match(/Price:\s*₹?([\d,]+)/i);
    const colorMatch = block.match(/Color:\s*(.+)/i);
    const idMatch = block.match(/Product ID:\s*(prod_\d+)/i);

    if (nameMatch && priceMatch) {
      products.push({
        id: idMatch?.[1] || `prod_${Date.now()}`,
        name: nameMatch[1].trim(),
        brand: brandMatch?.[1]?.trim() || "Unknown",
        price: parseInt(priceMatch[1].replace(/,/g, ""), 10),
        color: colorMatch?.[1]?.trim() || "",
      });
    }
  }

  return products;
}
