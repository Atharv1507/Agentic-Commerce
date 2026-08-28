import { Warp } from "@paper-design/shaders-react";

/**
 * Ambient backdrop for full-bleed screens (landing, onboarding). Wraps the
 * paper-design "Warp" shader — the same engine behind the reference Framer
 * "AnimatedLiquidBackground" component — tuned to the Porcelain/Charcoal/
 * Sand/Taupe palette (charcoal background, taupe accent) instead of its
 * default presets. Retuned to the Black/Jet Black/Almond Cream/Khaki Beige/
 * Stone Brown palette: almond cream and khaki beige carry the field, the
 * sand/mustard blends are the moving warmth — true black is deliberately
 * left out of this shader so the app's one high-contrast accent stays
 * foreground UI, not the backdrop every screen sits on. The wash on top is
 * heavier than the dark version needed — bright hues bloom far more on a
 * light ground.
 */
export default function LiquidBackground({ children, className = "" }) {
  return (
    <div className={`relative min-h-screen w-full overflow-hidden bg-background ${className}`}>
      <div className="pointer-events-none absolute inset-0 z-0">
        <Warp
          style={{ width: "100%", height: "100%" }}
          colors={["#eae0d5", "#8e7e67", "#d9c7ac", "#c6ac8f"]}
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
