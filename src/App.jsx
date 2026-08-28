import { AnimatePresence, LayoutGroup, motion } from "framer-motion";
import useSession from "@/hooks/useSession";
import useChat from "@/hooks/useChat";
import useChatThreads from "@/hooks/useChatThreads";
import LiquidBackground from "@/components/ui/LiquidBackground";
import OnboardingScreen from "@/components/onboarding/OnboardingScreen";
import WelcomeScreen from "@/components/welcome/WelcomeScreen";
import ChatWindow from "@/components/chat/ChatWindow";
import ChatSidebar from "@/components/chat/ChatSidebar";
import FloatingCartButton from "@/components/cart/FloatingCartButton";
import CartModal from "@/components/cart/CartModal";
import SettingsModal from "@/components/settings/SettingsModal";
import ActivityLogPanel from "@/components/activity/ActivityLogPanel";
import SpendLimitDialog from "@/components/checkout/SpendLimitDialog";
import { useState } from "react";

function App() {
  const {
    session,
    step,
    completeOnboarding,
    skipOnboarding,
    updateProfile,
    mergeProfile,
    startShopping,
    goHome,
    clearSession,
  } = useSession();
  // Details the agent collects mid-chat (an address at checkout, say) land in
  // the local session too, so Settings never shows a stale profile.
  const chat = useChat(session, { onProfileSynced: mergeProfile, onSessionMissing: clearSession });
  const { threads, createThread, switchThread, deleteThread, seenProducts } = useChatThreads(session, chat);
  const [cartOpen, setCartOpen] = useState(false);
  const [settingsOpen, setSettingsOpen] = useState(false);
  const [activityOpen, setActivityOpen] = useState(false);

  const enterChatWithThread = (id) => {
    switchThread(id);
    startShopping();
  };

  return (
    <LiquidBackground>
      <AnimatePresence mode="wait">
        {step === "onboarding" && (
          <motion.div key="onboarding" initial={{ opacity: 0 }} animate={{ opacity: 1 }} exit={{ opacity: 0 }}>
            <OnboardingScreen onComplete={completeOnboarding} onSkip={skipOnboarding} />
          </motion.div>
        )}

        {step === "welcome" && (
          <motion.div key="welcome" initial={{ opacity: 0 }} animate={{ opacity: 1 }} exit={{ opacity: 0 }}>
            <WelcomeScreen
              name={session?.name}
              onContinue={startShopping}
              threads={threads}
              onSelectThread={enterChatWithThread}
            />
          </motion.div>
        )}

        {step === "chat" && (
          <motion.div
            key="chat"
            className="flex h-screen"
            initial={{ opacity: 0 }}
            animate={{ opacity: 1 }}
            exit={{ opacity: 0 }}
          >
            <ChatSidebar
              threads={threads}
              seenProducts={seenProducts}
              cart={chat.cart}
              assistantName={session?.assistantName}
              onSelectThread={switchThread}
              onNewChat={createThread}
              onDeleteThread={deleteThread}
              onGoHome={goHome}
              onOpenSettings={() => setSettingsOpen(true)}
              onOpenActivityLog={() => setActivityOpen(true)}
              onAddToCart={chat.addToCart}
              userSize={session?.size}
            />

            <div className="flex min-h-0 min-w-0 flex-1 flex-col">
              <ChatWindow
                messages={chat.messages}
                isTyping={chat.isTyping}
                progress={chat.progress}
                onSend={chat.sendMessage}
                onOptionSelect={chat.selectOption}
                onAnswerPreferences={chat.answerPreferences}
                onSkipPreferences={chat.skipPreferences}
                cart={chat.cart}
                onAddToCart={chat.addToCart}
                assistantName={session?.assistantName}
                userSize={session?.size}
              />
            </div>

            <LayoutGroup>
              <AnimatePresence>
                {!cartOpen && chat.cart.length > 0 && (
                  <FloatingCartButton key="fab" count={chat.cart.reduce((n, item) => n + (item.quantity || 1), 0)} onClick={() => setCartOpen(true)} />
                )}
                {cartOpen && (
                  <CartModal
                    key="modal"
                    items={chat.cart}
                    onClose={() => setCartOpen(false)}
                    onConfirm={() => {
                      chat.confirmOrder();
                      setCartOpen(false);
                    }}
                    onRemove={chat.removeFromCart}
                    onChangeSize={chat.changeCartSize}
                  />
                )}
              </AnimatePresence>
            </LayoutGroup>

            <SettingsModal
              open={settingsOpen}
              onOpenChange={setSettingsOpen}
              session={session}
              onSave={updateProfile}
            />

            <ActivityLogPanel open={activityOpen} onOpenChange={setActivityOpen} session={session} />

            <SpendLimitDialog
              open={Boolean(chat.spendLimitBlock)}
              onOpenChange={(v) => !v && chat.dismissSpendLimitBlock()}
              amountInr={chat.spendLimitBlock?.amountInr}
              spendLimit={chat.spendLimitBlock?.spendLimit}
              onConfirm={chat.confirmSpendLimitOverride}
              onCancel={chat.dismissSpendLimitBlock}
            />
          </motion.div>
        )}
      </AnimatePresence>
    </LiquidBackground>
  );
}

export default App;
