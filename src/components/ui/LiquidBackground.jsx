import { Warp } from "@paper-design/shaders-react";

/**
 * Ambient backdrop for full-bleed screens (landing, onboarding). Wraps the
 * paper-design "Warp" shader — the same engine behind the reference Framer
 * "AnimatedLiquidBackground" component — tuned to the Porcelain/Charcoal/
 * Sand/Taupe palette (charcoal background, taupe accent) instead of its
 * default presets. Retuned to the Tomato/Platinum/Soft Linen/Gunmetal/Sandy
 * Brown palette: linen and platinum carry the field, sandy brown and mustard
 * are the moving warmth — tomato is deliberately left out of this shader so
 * the app's one bright-orange accent stays foreground UI, not the backdrop
 * every screen sits on. The wash on top is heavier than the dark version
 * needed — bright hues bloom far more on a light ground.
 */
export default function LiquidBackground({ children, className = "" }) {
  return (
    <div className={`relative min-h-screen w-full overflow-hidden bg-background ${className}`}>
      <div className="pointer-events-none absolute inset-0 z-0">
        <Warp
          style={{ width: "100%", height: "100%" }}
          colors={["#e0dfd5", "#f09d51", "#d9ae34", "#e8e9eb"]}
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
        <div className="absolute inset-0 bg-gradient-to-b from-background/85 via-background/60 to-background/90" />
      </div>

      <div className="relative z-10">{children}</div>
    </div>
  );
}
