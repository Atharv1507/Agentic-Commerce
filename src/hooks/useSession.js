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
  size: "",
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

  // The browser's copy of "you are onboarded" and the server's list of accounts
  // can disagree — most obviously when the sessions store is cleared on the
  // server while a browser still holds a session for an account that no longer
  // exists. Without this check the app goes straight to chat and every message
  // comes back 404, reading to the shopper as "something went wrong" forever,
  // fixable only by clearing site data by hand.
  //
  // Only a definitive 404 resets. A network error means the backend is down or
  // unreachable, which says nothing about whether the account exists — wiping a
  // profile over a failed request would be a far worse bug than the one this
  // fixes.
  useEffect(() => {
    const email = session?.email;
    if (!email || !session?.isOnboarded) return;

    let active = true;
    (async () => {
      let res;
      try {
        res = await fetch(`${API_BASE}/session/${encodeURIComponent(email)}`);
      } catch {
        return; // Offline or backend down — keep what we have.
      }
      if (!active || res.status !== 404) return;

      console.info("Server has no account for this session; starting fresh.");
      localStorage.removeItem(STORAGE_KEY);
      setSession(null);
      setStep("onboarding");
    })();

    return () => {
      active = false;
    };
    // Runs once per mount: this is a reconciliation on load, not something to
    // repeat on every profile edit.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

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
          size: data.size,
          payment_method: data.payment_method,
          spend_limit: data.spend_limit,
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
      size: data.size,
      paymentMethod: data.payment_method,
      // Per-order auto-approve ceiling, edited only in Settings — never
      // through chat (update_profile has no such field on the backend).
      spendLimit: data.spend_limit ?? 5000,
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
        size: data.size ?? session?.size,
        payment_method: data.payment_method ?? session?.paymentMethod,
        spend_limit: data.spend_limit ?? session?.spendLimit,
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
        size: "size",
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

  const clearSession = useCallback(() => {
    localStorage.removeItem(STORAGE_KEY);
    setSession(null);
    setStep("onboarding");
  }, []);

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
