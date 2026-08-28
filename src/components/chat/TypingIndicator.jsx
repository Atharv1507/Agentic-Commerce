import { useEffect, useState } from "react";
import { AnimatePresence, motion } from "framer-motion";

// Shown only while we're waiting on the backend's first progress event, or if
// streaming isn't available at all. Deliberately vague — anything specific here
// would be a guess, and the real labels arrive over SSE within a second.
const WAITING_LABELS = [
  "Getting started",
  "Thinking it through",
  "Still working on it",
  "Nearly there",
];

// How long a turn has to run before we reassure the user it hasn't stalled.
const REASSURE_AFTER_MS = 6000;

export default function TypingIndicator({ progress }) {
  const [fallbackIndex, setFallbackIndex] = useState(0);
  const [elapsed, setElapsed] = useState(0);

  useEffect(() => {
    const started = Date.now();
    const timer = setInterval(() => setElapsed(Date.now() - started), 500);
    return () => clearInterval(timer);
  }, []);

  // Only cycle the placeholder copy while no real event has arrived.
  useEffect(() => {
    if (progress) return;
    const timer = setInterval(
      () => setFallbackIndex((i) => Math.min(i + 1, WAITING_LABELS.length - 1)),
      2600
    );
    return () => clearInterval(timer);
  }, [progress]);

  const label = progress?.label || WAITING_LABELS[fallbackIndex];
  const round = progress?.round;
  const maxRounds = progress?.max_rounds;
  const showReassurance = elapsed > REASSURE_AFTER_MS;

  return (
    <div className="flex w-full justify-start">
      <div className="flex max-w-md flex-col gap-1.5 rounded-2xl rounded-bl-md border border-mustard/20 bg-card px-5 py-3">
        <div className="flex items-center gap-2.5">
          {/* Keyed on the label so each new stage crossfades instead of snapping */}
          <AnimatePresence mode="wait" initial={false}>
            <motion.span
              key={label}
              className="shimmer text-sm font-medium"
              initial={{ opacity: 0, y: 4 }}
              animate={{ opacity: 1, y: 0 }}
              exit={{ opacity: 0, y: -4 }}
              transition={{ duration: 0.18 }}
            >
              {label}
            </motion.span>
          </AnimatePresence>

          {[0, 1, 2].map((i) => (
            <motion.div
              key={i}
              className="size-2 rounded-full bg-mustard shadow-[0_0_6px_var(--color-mustard)]"
              animate={{ y: [0, -6, 0], opacity: [0.5, 1, 0.5] }}
              transition={{
                duration: 0.6,
                repeat: Infinity,
                delay: i * 0.15,
                ease: "easeInOut",
              }}
            />
          ))}
        </div>

        {(showReassurance || round > 1) && (
          <motion.p
            className="text-xs leading-snug text-muted-foreground"
            initial={{ opacity: 0 }}
            animate={{ opacity: 1 }}
          >
            {round > 1
              ? `Checking with the seller again (round ${round}${maxRounds ? ` of ${maxRounds}` : ""}) — I'll be back with you shortly.`
              : "I'm going back and forth with the seller to get this right — I'll be back with you shortly."}
          </motion.p>
        )}
      </div>
    </div>
  );
}
