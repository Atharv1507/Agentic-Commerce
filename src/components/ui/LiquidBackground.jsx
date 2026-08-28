import { Warp } from "@paper-design/shaders-react";

/**
 * Ambient backdrop for full-bleed screens (landing, onboarding). Wraps the
 * paper-design "Warp" shader — the same engine behind the reference Framer
 * "AnimatedLiquidBackground" component — tuned to the Porcelain/Charcoal/
 * Sand/Taupe palette (charcoal background, taupe accent) instead of its
 * default presets.
 */
export default function LiquidBackground({ children, className = "" }) {
  return (
    <div className={`relative min-h-screen w-full overflow-hidden bg-background ${className}`}>
      <div className="pointer-events-none absolute inset-0 z-0">
        <Warp
          style={{ width: "100%", height: "100%" }}
          colors={["#1e1e1e", "#6c584c", "#453b35", "#1e1e1e"]}
          proportion={0.4}
          softness={1.1}
          distortion={0.15}
          swirl={0.5}
          swirlIterations={8}
          shapeScale={0.2}
          shape="edge"
          rotation={20}
          scale={1}
          speed={1.1}
        />
        <div className="absolute inset-0 bg-gradient-to-b from-background/70 via-background/30 to-background/85" />
      </div>

      <div className="relative z-10">{children}</div>
    </div>
  );
}
