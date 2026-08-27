import { useState, useEffect } from "react";

const STORAGE_KEY = "shopper_agent_session";

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

  const completeOnboarding = async (data) => {
    const email = data.email?.toLowerCase();

    try {
      await fetch("http://localhost:8000/onboarding", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          email,
          phone: data.phone,
          address: data.address,
          gender: data.gender,
          payment_method: data.payment_method,
        }),
      });
    } catch (e) {
      console.warn("Backend not available, continuing anyway");
    }

    const newSession = {
      email,
      name: data.name,
      phone: data.phone,
      address: data.address,
      gender: data.gender,
      paymentMethod: data.payment_method,
      isOnboarded: true,
    };

    setSession(newSession);
    setStep("welcome");
  };

  const startShopping = () => {
    setStep("chat");
  };

  const clearSession = () => {
    localStorage.removeItem(STORAGE_KEY);
    setSession(null);
    setStep("onboarding");
  };

  return { session, step, completeOnboarding, startShopping, clearSession };
}
