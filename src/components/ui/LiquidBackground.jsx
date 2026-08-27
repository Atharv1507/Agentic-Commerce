import { motion } from "framer-motion";

const blobs = [
  { color: "rgba(212, 160, 48, 0.3)", x: "20%", y: "30%", size: 400 },
  { color: "rgba(232, 184, 74, 0.2)", x: "70%", y: "60%", size: 350 },
  { color: "rgba(180, 120, 30, 0.25)", x: "50%", y: "20%", size: 300 },
  { color: "rgba(255, 200, 80, 0.15)", x: "80%", y: "80%", size: 250 },
];

export default function LiquidBackground({ children, className = "" }) {
  return (
    <div className={`relative min-h-screen w-full overflow-hidden ${className}`}>
      <div className="absolute inset-0 z-0">
        <div
          className="absolute inset-0"
          style={{
            background:
              "radial-gradient(ellipse at 30% 20%, rgba(212, 160, 48, 0.08) 0%, transparent 50%), radial-gradient(ellipse at 70% 80%, rgba(232, 184, 74, 0.06) 0%, transparent 50%), radial-gradient(ellipse at 50% 50%, rgba(180, 120, 30, 0.04) 0%, transparent 60%)",
          }}
        />
        {blobs.map((blob, i) => (
          <motion.div
            key={i}
            className="absolute rounded-full blur-3xl"
            style={{
              background: blob.color,
              width: blob.size,
              height: blob.size,
              left: blob.x,
              top: blob.y,
              transform: "translate(-50%, -50%)",
            }}
            animate={{
              x: [0, 30, -20, 10, 0],
              y: [0, -25, 15, -10, 0],
              scale: [1, 1.1, 0.95, 1.05, 1],
            }}
            transition={{
              duration: 20 + i * 5,
              repeat: Infinity,
              ease: "easeInOut",
            }}
          />
        ))}
        <div className="absolute inset-0 bg-gradient-to-b from-background/80 via-background/40 to-background/90" />
      </div>
      <div className="relative z-10">{children}</div>
    </div>
  );
}
