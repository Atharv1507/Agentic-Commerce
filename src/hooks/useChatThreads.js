import { useState, useEffect, useCallback, useMemo } from "react";

const API_BASE = import.meta.env.VITE_API_BASE_URL || "http://localhost:8000";

// Transcripts live here (localStorage) and the agent's matching memory lives on
// the backend, keyed by the SAME thread id — so the two can't drift. Switching
// chats no longer has to wipe anything: the backend keeps one history per
// thread, which is also what stops something said in this chat from surfacing
// in another one.
//
// Deleting a chat is the one case where the backend has to be told, since its
// copy of a conversation the user just removed should not outlive it.
function forgetBackendThread(email, threadId) {
  if (!email || !threadId) return;
  fetch(`${API_BASE}/session/${email}/thread/${threadId}`, { method: "DELETE" }).catch(() => {});
}

function storageKey(email) {
  return `shopper_agent_threads_${email || "anon"}`;
}

function freshThread(name) {
  return {
    id: crypto.randomUUID?.() || `thread-${Date.now()}-${Math.random()}`,
    title: null,
    createdAt: Date.now(),
    updatedAt: Date.now(),
    messages: [
      {
        id: "greeting",
        role: "agent",
        content: `Hey ${name || "there"}! I'm your shopping assistant. What can I help you find today?`,
      },
    ],
    cart: [],
  };
}

function deriveTitle(thread) {
  if (thread.title) return thread.title;
  const firstUserMsg = thread.messages.find((m) => m.role === "user");
  if (!firstUserMsg) return "New chat";
  const text = firstUserMsg.content.trim();
  return text.length > 42 ? `${text.slice(0, 42)}…` : text;
}

function loadThreads(email) {
  try {
    const stored = localStorage.getItem(storageKey(email));
    const parsed = stored ? JSON.parse(stored) : [];
    return Array.isArray(parsed) && parsed.length > 0 ? parsed : null;
  } catch {
    return null;
  }
}

export default function useChatThreads(session, chat) {
  const email = session?.email;
  const [threads, setThreads] = useState(() => loadThreads(email) || [freshThread(session?.name)]);
  const [activeId, setActiveId] = useState(() => threads[0]?.id);

  // Push the active thread's saved conversation into the chat hook. Seeded to
  // a sentinel (not `email`) so this also fires on the VERY FIRST render, not
  // just when `email` later changes — otherwise a returning user's history
  // never gets loaded into the chat hook at all on page reload. Done during
  // render, not an effect, per React's "adjusting state when a prop changes"
  // pattern, so the chat hook never renders a stale thread's messages even
  // for a single frame.
  const [syncedEmail, setSyncedEmail] = useState(undefined);
  if (email && email !== syncedEmail) {
    const loaded = loadThreads(email) || [freshThread(session?.name)];
    setSyncedEmail(email);
    setThreads(loaded);
    setActiveId(loaded[0].id);
    chat.restoreThread(loaded[0]);
  }

  // `threads` only holds frozen snapshots of INACTIVE threads — the active
  // one's messages/cart live in the chat hook itself and are merged in below,
  // so this never needs to mirror chat state back into React state via an
  // effect. Persisting to localStorage is a pure side effect (no setState),
  // which is exactly what an effect should be doing.
  const liveThreads = useMemo(
    () => threads.map((t) => (t.id === activeId ? { ...t, messages: chat.messages, cart: chat.cart } : t)),
    [threads, activeId, chat.messages, chat.cart]
  );

  useEffect(() => {
    if (email !== syncedEmail || !activeId) return;
    try {
      localStorage.setItem(storageKey(email), JSON.stringify(liveThreads));
    } catch {
      // best-effort only
    }
  }, [liveThreads, activeId, email, syncedEmail]);

  const snapshotActiveThread = useCallback(() => {
    if (!activeId) return;
    setThreads((prev) =>
      prev.map((t) => {
        if (t.id !== activeId) return t;
        // Merely viewing/leaving a thread isn't "activity" — only bump the
        // recency timestamp if messages or cart actually changed since the
        // last snapshot, so switching threads never reorders the sidebar.
        const changed = t.messages.length !== chat.messages.length || t.cart.length !== chat.cart.length;
        return { ...t, messages: chat.messages, cart: chat.cart, updatedAt: changed ? Date.now() : t.updatedAt };
      })
    );
  }, [activeId, chat.messages, chat.cart]);

  const createThread = useCallback(() => {
    snapshotActiveThread();
    const thread = freshThread(session?.name);
    setThreads((prev) => [thread, ...prev]);
    setActiveId(thread.id);
    chat.restoreThread(thread);
  }, [snapshotActiveThread, chat, session?.name]);

  const switchThread = useCallback(
    (id) => {
      if (id === activeId) return;
      const thread = liveThreads.find((t) => t.id === id);
      if (!thread) return;
      snapshotActiveThread();
      setActiveId(id);
      chat.restoreThread(thread);
    },
    [liveThreads, activeId, snapshotActiveThread, chat]
  );

  // Deleting the thread you're looking at has to leave *something* on screen,
  // so the newest survivor becomes active (or a fresh thread if that was the
  // last one). Either way the agent forgets the deleted conversation, since it
  // is one the user can no longer see.
  const deleteThread = useCallback(
    (id) => {
      const remaining = liveThreads.filter((t) => t.id !== id);
      forgetBackendThread(email, id);

      if (id !== activeId) {
        setThreads(remaining);
        return;
      }

      const next = [...remaining].sort((a, b) => b.updatedAt - a.updatedAt)[0] || freshThread(session?.name);
      setThreads(remaining.length ? remaining : [next]);
      setActiveId(next.id);
      chat.restoreThread(next);
    },
    [liveThreads, activeId, chat, session?.name, email]
  );

  const orderedThreads = useMemo(
    () =>
      [...liveThreads]
        .sort((a, b) => b.updatedAt - a.updatedAt)
        .map((t) => ({ ...t, title: deriveTitle(t), isActive: t.id === activeId })),
    [liveThreads, activeId]
  );

  const activeThread = useMemo(() => liveThreads.find((t) => t.id === activeId), [liveThreads, activeId]);

  const seenProducts = useMemo(() => {
    if (!activeThread) return [];
    const seen = new Map();
    for (const msg of activeThread.messages) {
      if (msg.type !== "products") continue;
      for (const product of msg.products || []) {
        seen.set(product.id, product);
      }
    }
    return [...seen.values()].reverse();
  }, [activeThread]);

  return { threads: orderedThreads, activeId, createThread, switchThread, deleteThread, seenProducts };
}
