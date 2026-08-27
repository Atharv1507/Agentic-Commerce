import { AnimatePresence, motion } from "framer-motion";
import useSession from "@/hooks/useSession";
import useChat from "@/hooks/useChat";
import LiquidBackground from "@/components/ui/LiquidBackground";
import OnboardingScreen from "@/components/onboarding/OnboardingScreen";
import WelcomeScreen from "@/components/welcome/WelcomeScreen";
import ChatWindow from "@/components/chat/ChatWindow";
import ProductGrid from "@/components/products/ProductGrid";
import FloatingCartButton from "@/components/cart/FloatingCartButton";
import CartModal from "@/components/cart/CartModal";
import { useState } from "react";

function App() {
  const { session, step, completeOnboarding, startShopping } = useSession();
  const chat = useChat(session);
  const [cartOpen, setCartOpen] = useState(false);

  // Find last products message for rendering grid
  const lastProductsMsg = [...chat.messages]
    .reverse()
    .find((m) => m.type === "products" && m.products?.length > 0);

  return (
    <LiquidBackground>
      <AnimatePresence mode="wait">
        {step === "onboarding" && (
          <motion.div
            key="onboarding"
            initial={{ opacity: 0 }}
            animate={{ opacity: 1 }}
            exit={{ opacity: 0 }}
          >
            <OnboardingScreen onComplete={completeOnboarding} />
          </motion.div>
        )}

        {step === "welcome" && (
          <motion.div
            key="welcome"
            initial={{ opacity: 0 }}
            animate={{ opacity: 1 }}
            exit={{ opacity: 0 }}
          >
            <WelcomeScreen name={session?.name} onContinue={startShopping} />
          </motion.div>
        )}

        {step === "chat" && (
          <motion.div
            key="chat"
            className="h-screen flex flex-col"
            initial={{ opacity: 0 }}
            animate={{ opacity: 1 }}
            exit={{ opacity: 0 }}
          >
            <ChatWindow
              messages={chat.messages}
              isTyping={chat.isTyping}
              onSend={chat.sendMessage}
              onOptionSelect={chat.selectOption}
            />

            {/* Product grid rendered below chat messages when products are shown */}
            {lastProductsMsg && (
              <div className="border-t border-border bg-background/80 backdrop-blur-sm max-h-[40vh] overflow-y-auto">
                <ProductGrid
                  products={lastProductsMsg.products}
                  cart={chat.cart}
                  onAddToCart={chat.addToCart}
                />
              </div>
            )}

            <FloatingCartButton
              count={chat.cart.length}
              onClick={() => setCartOpen(true)}
            />

            <CartModal
              isOpen={cartOpen}
              items={chat.cart}
              onClose={() => setCartOpen(false)}
              onConfirm={() => {
                chat.confirmOrder();
                setCartOpen(false);
              }}
              onRemove={chat.removeFromCart}
            />
          </motion.div>
        )}
      </AnimatePresence>
    </LiquidBackground>
  );
}

export default App;
