import { useEffect, useState } from "react";

const API_BASE = import.meta.env.VITE_API_BASE_URL || "http://localhost:8000";

// Fetches fresh every time the panel opens rather than once — unlike saved
// preferences, activity changes on nearly every turn, so there's no value in
// caching it across opens.
export default function useActivityLog(session, open) {
  const [entries, setEntries] = useState(null);

  useEffect(() => {
    if (!open || !session?.email) return;
    let active = true;

    fetch(`${API_BASE}/session/${session.email}/logs`)
      .then((res) => (res.ok ? res.json() : { entries: [] }))
      .then((data) => active && setEntries(data.entries || []))
      .catch(() => active && setEntries([]));

    return () => {
      active = false;
    };
  }, [open, session?.email]);

  return { entries };
}
