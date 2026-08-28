import { useState, useEffect, useCallback } from "react";
import { DEFAULT_ASSISTANT_NAME } from "@/lib/utils";

const STORAGE_KEY = "shopper_agent_session";
const API_BASE = import.meta.env.VITE_API_BASE_URL || "http://localhost:8000";

// Deliberately empty (not placeholder junk like "COD"/"Other"): checkout_cart
// on the backend only asks the user for a field when it's falsy in session.
// Sending fake values here would make every skipped guest look fully
// onboarded and the agent would never ask for real address/payment at checkout.
// assistant_name is the one exception — it's cosmetic only, so a skipped
// guest still gets the branded default instead of an empty avatar.
const GUEST_DEFAULTS = {
  name: "Guest",
  assistant_name: DEFAULT_ASSISTANT_NAME,
  phone: "",
  address: "",
  gender: "",
  payment_method: "",
};

export default function useSession() {
  const [session, setSession] = useState(() => {
    try {
      const stored = localStorage.getItem(STORAGE_KEY);
      return stored ? JSON.parse(stored) : null;
    } catch {
      return null;
    }
  });

  const [step, setStep] = useState(() => {
    if (!session) return "onboarding";
    if (!session.isOnboarded) return "onboarding";
    return "chat";
  });

  useEffect(() => {
    if (session) {
      localStorage.setItem(STORAGE_KEY, JSON.stringify(session));
    }
  }, [session]);

  const submitOnboarding = useCallback(async (data) => {
    const email = (data.email || "").toLowerCase();

    try {
      await fetch(`${API_BASE}/onboarding`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          email,
          name: data.name,
          phone: data.phone,
          address: data.address,
          gender: data.gender,
          payment_method: data.payment_method,
        }),
      });
    } catch {
      console.warn("Backend not available, continuing anyway");
    }

    const newSession = {
      email,
      name: data.name,
      assistantName: data.assistant_name || DEFAULT_ASSISTANT_NAME,
      phone: data.phone,
      address: data.address,
      gender: data.gender,
      paymentMethod: data.payment_method,
      isOnboarded: true,
    };

    setSession(newSession);
    return newSession;
  }, []);

  const completeOnboarding = useCallback(
    async (data) => {
      await submitOnboarding(data);
      setStep("welcome");
    },
    [submitOnboarding]
  );

  // Skips straight to chat with placeholder defaults for anything not yet
  // answered — real details can always be filled in later from Settings.
  const skipOnboarding = useCallback(
    async (partial = {}) => {
      const email = partial.email || session?.email || `guest-${Date.now()}@shopper.local`;
      await submitOnboarding({ ...GUEST_DEFAULTS, ...partial, email });
      setStep("chat");
    },
    [submitOnboarding, session]
  );

  const updateProfile = useCallback(
    async (data) => {
      await submitOnboarding({
        email: session?.email,
        name: data.name ?? session?.name,
        assistant_name: data.assistant_name ?? session?.assistantName,
        phone: data.phone ?? session?.phone,
        address: data.address ?? session?.address,
        gender: data.gender ?? session?.gender,
        payment_method: data.payment_method ?? session?.paymentMethod,
      });
    },
    [session, submitOnboarding]
  );

  // Fold details the agent collected during a chat back into the local session.
  // Local-only on purpose: the backend is where they came from, so posting them
  // back would be a pointless round trip — this just keeps Settings honest, so
  // an address given at checkout is visible in the profile straight away.
  const mergeProfile = useCallback((profile) => {
    if (!profile) return;
    setSession((prev) => {
      if (!prev) return prev;
      const next = { ...prev };
      const map = {
        name: "name",
        phone: "phone",
        address: "address",
        gender: "gender",
        payment_method: "paymentMethod",
      };
      let changed = false;
      for (const [from, to] of Object.entries(map)) {
        if (profile[from] && profile[from] !== next[to]) {
          next[to] = profile[from];
          changed = true;
        }
      }
      return changed ? next : prev;
    });
  }, []);

  const startShopping = () => {
    setStep("chat");
  };

  const goHome = () => {
    setStep("welcome");
  };

  const clearSession = () => {
    localStorage.removeItem(STORAGE_KEY);
    setSession(null);
    setStep("onboarding");
  };

  return {
    session,
    step,
    completeOnboarding,
    skipOnboarding,
    updateProfile,
    mergeProfile,
    startShopping,
    goHome,
    clearSession,
  };
}
