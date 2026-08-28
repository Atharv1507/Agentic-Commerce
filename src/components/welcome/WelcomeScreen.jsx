import { motion } from "framer-motion";
import { ArrowUpRight, Sparkle, ShoppingBag, MessageCircle } from "lucide-react";

function getGreeting() {
  const hour = new Date().getHours();
  if (hour < 12) return "Good morning";
  if (hour < 17) return "Good afternoon";
  return "Good evening";
}

function relativeTime(ts) {
  const diffMin = Math.round((Date.now() - ts) / 60000);
  if (diffMin < 1) return "just now";
  if (diffMin < 60) return `${diffMin}m ago`;
  const diffHr = Math.round(diffMin / 60);
  if (diffHr < 24) return `${diffHr}h ago`;
  return `${Math.round(diffHr / 24)}d ago`;
}

// A fanned stack of recent conversations, styled after the same hover-reveal
// card language as the hero CTA below — this is purely local history (no
// backend persistence), so it only appears once there's something to show.
function HistoryStack({ threads, onSelectThread }) {
  const recent = threads.filter((t) => t.title !== "New chat").slice(0, 5);
  if (recent.length === 0) return null;

  return (
    <motion.div
      className="mt-16 w-full max-w-4xl"
      initial={{ opacity: 0, y: 20 }}
      animate={{ opacity: 1, y: 0 }}
      transition={{ delay: 0.9, duration: 0.6 }}
    >
      <p className="mb-4 text-center text-xs tracking-[0.25em] text-muted-foreground/70 uppercase lg:text-left">
        Pick up where you left off
      </p>
      <div className="flex flex-wrap justify-center gap-4 lg:justify-start">
        {recent.map((thread, i) => (
          <motion.button
            key={thread.id}
            onClick={() => onSelectThread(thread.id)}
            className="group relative flex h-40 w-44 shrink-0 flex-col justify-between overflow-hidden p-5 text-left"
            style={{
              borderRadius: "1.25rem",
              background:
                "radial-gradient(130% 130% at 20% 10%, rgba(108,88,76,0.35) 0%, rgba(39,39,39,0.85) 45%, rgba(30,30,30,1) 100%)",
            }}
            initial={{ opacity: 0, y: 14, rotate: i % 2 === 0 ? -2 : 2 }}
            animate={{ opacity: 1, y: 0, rotate: 0 }}
            transition={{ delay: 1 + i * 0.08 }}
            whileHover={{ y: -4, scale: 1.02 }}
          >
            <div className="pointer-events-none absolute inset-0 border border-white/10" style={{ borderRadius: "1.25rem" }} />
            <MessageCircle className="relative z-[1] size-4 text-primary/70" />
            <div className="relative z-[1]">
              <p className="line-clamp-2 text-sm leading-snug text-white/90">{thread.title}</p>
              <p className="mt-1.5 text-xs text-white/40">{relativeTime(thread.updatedAt)}</p>
            </div>
          </motion.button>
        ))}
      </div>
    </motion.div>
  );
}

export default function WelcomeScreen({ name, onContinue, threads = [], onSelectThread }) {
  return (
    <div className="flex min-h-screen flex-col items-center justify-center gap-14 p-8 py-16">
    <div className="flex flex-col items-center gap-14 lg:flex-row lg:gap-20">
      {/* Text column */}
      <motion.div
        className="max-w-lg text-center lg:text-left"
        initial={{ opacity: 0, y: 24 }}
        animate={{ opacity: 1, y: 0 }}
        transition={{ duration: 0.8, ease: "easeOut" }}
      >
        <motion.div
          className="mb-6 flex items-center justify-center gap-2 text-xs tracking-[0.25em] text-primary uppercase lg:justify-start"
          initial={{ opacity: 0 }}
          animate={{ opacity: 1 }}
          transition={{ delay: 0.2 }}
        >
          <Sparkle className="size-3.5" />
          Personal Shopping, Reimagined
        </motion.div>

        <motion.h1
          className="font-hero text-4xl md:text-5xl"
          initial={{ opacity: 0, y: 10 }}
          animate={{ opacity: 1, y: 0 }}
          transition={{ delay: 0.4 }}
        >
          {getGreeting()}, <span className="emphasis">{name || "there"}</span>
        </motion.h1>

        <motion.p
          className="mt-5 text-lg leading-relaxed text-muted-foreground"
          initial={{ opacity: 0 }}
          animate={{ opacity: 1 }}
          transition={{ delay: 0.6 }}
        >
          Your concierge is ready — tell it what you're after, and it will find, compare,
          and check out for you.
        </motion.p>
      </motion.div>

      {/* Hero centerpiece — hover-reveal card, always-clickable for mobile/no-hover */}
      <motion.button
        onClick={onContinue}
        className="group relative flex h-[22rem] w-[19rem] shrink-0 flex-col justify-between overflow-hidden p-9 text-left sm:h-[26rem] sm:w-[22.5rem]"
        style={{
          borderRadius: "1.75rem",
          background:
            "radial-gradient(120% 120% at 15% 10%, rgba(145,126,112,0.4) 0%, rgba(39,39,39,0.9) 45%, rgba(30,30,30,1) 100%)",
        }}
        initial={{ opacity: 0, scale: 0.94 }}
        animate={{ opacity: 1, scale: 1 }}
        transition={{ delay: 0.5, duration: 0.7, ease: "easeOut" }}
        whileTap={{ scale: 0.98 }}
      >
        <div className="pointer-events-none absolute inset-0 border border-white/10" style={{ borderRadius: "1.75rem" }} />

        {/* dark blur overlay, fades in on hover — matches the Hover Product Card reference */}
        <motion.div
          className="pointer-events-none absolute inset-0 bg-black/0"
          whileHover={{ backgroundColor: "rgba(0,0,0,0.25)", backdropFilter: "blur(4px)" }}
          transition={{ duration: 0.3 }}
        />

        <div className="relative z-[1] flex items-center justify-between">
          <span className="text-xs tracking-widest text-white/50 uppercase">Curated for you</span>
          <ArrowUpRight className="size-4 text-white/50 transition-transform group-hover:-translate-y-0.5 group-hover:translate-x-0.5" />
        </div>

        <div className="relative z-[1]">
          <motion.p
            className="font-hero text-2xl text-white"
            initial={{ opacity: 1, y: 0 }}
            whileHover={{ y: -2 }}
          >
            Step into the <span className="emphasis text-white">chat</span>
          </motion.p>
          <motion.p
            className="mt-2 max-w-[16rem] text-sm text-white/60 opacity-0 transition-opacity duration-300 group-hover:opacity-100"
          >
            One conversation, endless taste — describe what you want and let the agent do the rest.
          </motion.p>

          <motion.div
            className="mt-6 flex size-14 items-center justify-center rounded-full bg-primary text-primary-foreground shadow-lg shadow-primary/30"
            whileHover={{ scale: 1.08 }}
            transition={{ type: "spring", stiffness: 300, damping: 20 }}
          >
            <ShoppingBag className="size-6" />
          </motion.div>
        </div>
      </motion.button>
    </div>

    <HistoryStack threads={threads} onSelectThread={onSelectThread} />
    </div>
  );
}
