import { useEffect } from "react";
import { motion } from "framer-motion";
import { ArrowLeft, BarChart3, TriangleAlert } from "lucide-react";

import useMerchantAnalytics from "../../hooks/useMerchantAnalytics";

const rupees = (value) => `₹${(value || 0).toLocaleString("en-IN")}`;

// Section label idiom used across the app (receipts, sidebar).
const Label = ({ children }) => (
  <p className="text-xs uppercase tracking-widest text-muted-foreground">{children}</p>
);

const StatTile = ({ label, value, hint }) => (
  <div className="rounded-2xl border border-border bg-card p-5">
    <Label>{label}</Label>
    <p className="mt-2 font-hero text-2xl text-foreground">{value}</p>
    {hint ? <p className="mt-1 text-xs text-muted-foreground">{hint}</p> : null}
  </div>
);

// Hand-rolled rather than pulling in a charting library: the app has none, one
// bar per row is all this needs, and a dependency would bring its own type
// scale and colour defaults to fight with the theme. Same reasoning as the
// hand-built timeline in TrackOrderView.
const BarRow = ({ label, value, max, caption, tone = "sand" }) => {
  const pct = max > 0 ? Math.max((value / max) * 100, 2) : 0;
  const fill = { sand: "bg-sand", mustard: "bg-mustard", secondary: "bg-secondary" }[tone];
  return (
    <div className="space-y-1.5">
      <div className="flex items-baseline justify-between gap-4">
        <p className="truncate text-sm text-foreground">{label}</p>
        <p className="shrink-0 text-sm text-muted-foreground">{caption}</p>
      </div>
      <div className="h-2 overflow-hidden rounded-full bg-secondary/40">
        <div className={`h-full rounded-full ${fill}`} style={{ width: `${pct}%` }} />
      </div>
    </div>
  );
};

export default function MerchantDashboard({ onClose }) {
  const { analytics, error } = useMerchantAnalytics();

  useEffect(() => {
    const handleKeyDown = (e) => e.key === "Escape" && onClose();
    window.addEventListener("keydown", handleKeyDown);
    return () => window.removeEventListener("keydown", handleKeyDown);
  }, [onClose]);

  const byBuyer = analytics?.revenue_by_buyer || [];
  const topBuyerRevenue = Math.max(...byBuyer.map((b) => b.revenue_inr), 0);
  const topProducts = analytics?.top_products || [];
  const topProductRevenue = Math.max(...topProducts.map((p) => p.revenue_inr), 0);
  const campaigns = analytics?.campaign_impact?.by_campaign || [];
  const topCampaignRevenue = Math.max(...campaigns.map((c) => c.revenue_inr), 0);

  return (
    // `bg-background` is load-bearing: LiquidBackground wraps the whole app and
    // shows through anything translucent.
    <motion.div
      className="fixed inset-0 z-[70] flex flex-col bg-background"
      initial={{ opacity: 0 }}
      animate={{ opacity: 1 }}
      exit={{ opacity: 0 }}
      transition={{ duration: 0.2 }}
    >
      <div className="flex items-center gap-3 border-b border-border px-6 py-4 md:px-10">
        <button
          onClick={onClose}
          className="rounded-lg p-1.5 text-muted-foreground transition-colors hover:bg-secondary hover:text-foreground"
          aria-label="Back to chat"
        >
          <ArrowLeft className="size-4" />
        </button>
        <h1 className="font-hero text-xl">Merchant analytics</h1>
        <span className="ml-auto rounded-full border border-border px-2.5 py-1 text-[10px] uppercase tracking-widest text-muted-foreground">
          Developer view
        </span>
      </div>

      <div className="flex-1 overflow-y-auto px-6 py-8 md:px-10">
        {error ? (
          <div className="flex h-full flex-col items-center justify-center gap-3 text-center">
            <TriangleAlert className="size-8 text-muted-foreground/50" />
            <p className="max-w-sm text-sm text-muted-foreground">
              {error === "unauthorised"
                ? "The merchant service rejected the analytics key. Check MERCHANT_API_KEY on the seller agent and VITE_MERCHANT_KEY here."
                : "Could not reach the merchant service on port 8001. Is the seller agent running?"}
            </p>
          </div>
        ) : analytics === null ? (
          <p className="p-10 text-center text-sm text-muted-foreground">
            Loading the merchant's books…
          </p>
        ) : analytics.order_count === 0 ? (
          <div className="flex h-full flex-col items-center justify-center gap-3 text-center">
            <BarChart3 className="size-8 text-muted-foreground/50" />
            <p className="max-w-xs text-sm text-muted-foreground">
              No paid orders yet. Complete a checkout and this fills in.
            </p>
            {analytics.pending_orders > 0 ? (
              <p className="text-xs text-muted-foreground">
                {analytics.pending_orders} order(s) created but unpaid, worth{" "}
                {rupees(analytics.pending_value_inr)}.
              </p>
            ) : null}
          </div>
        ) : (
          <div className="mx-auto max-w-4xl space-y-10">
            <section className="grid gap-4 sm:grid-cols-2 lg:grid-cols-4">
              <StatTile
                label="Revenue"
                value={rupees(analytics.total_revenue_inr)}
                hint="Paid orders only"
              />
              <StatTile label="Orders" value={analytics.order_count} />
              <StatTile label="Avg order value" value={rupees(analytics.aov_inr)} />
              <StatTile
                label="Awaiting payment"
                value={analytics.pending_orders}
                hint={rupees(analytics.pending_value_inr)}
              />
            </section>

            {/* The metric that only exists once a merchant is transactable by
                more than one AI buyer — which agent is actually bringing money
                in. */}
            <section className="space-y-4">
              <div>
                <Label>Revenue by buyer agent</Label>
                <p className="mt-1 text-xs text-muted-foreground">
                  Attributed from the authenticated key on each order.
                </p>
              </div>
              <div className="space-y-4 rounded-2xl border border-border bg-card p-5">
                {byBuyer.map((buyer) => (
                  <BarRow
                    key={buyer.buyer_id}
                    label={buyer.buyer_id}
                    value={buyer.revenue_inr}
                    max={topBuyerRevenue}
                    tone="sand"
                    caption={`${rupees(buyer.revenue_inr)} · ${buyer.revenue_share_pct}% · ${buyer.order_count} order(s)`}
                  />
                ))}
              </div>
            </section>

            <section className="grid gap-4 sm:grid-cols-2">
              <div className="rounded-2xl border border-border bg-card p-5">
                <Label>Cross-sell attach rate</Label>
                <p className="mt-2 font-hero text-2xl">{analytics.attach_rate.rate_pct}%</p>
                <p className="mt-1 text-xs text-muted-foreground">
                  {analytics.attach_rate.orders_with_cross_sell} of {analytics.order_count} paid
                  orders included a suggested item, worth{" "}
                  {rupees(analytics.attach_rate.cross_sell_revenue_inr)}.
                </p>
              </div>
              <div className="rounded-2xl border border-border bg-card p-5">
                <Label>Discount given</Label>
                <p className="mt-2 font-hero text-2xl">
                  {rupees(analytics.campaign_impact.total_discount_inr)}
                </p>
                <p className="mt-1 text-xs text-muted-foreground">
                  {analytics.campaign_impact.discount_share_pct}% of list price, across{" "}
                  {analytics.campaign_impact.orders_with_campaign} order(s) (
                  {analytics.campaign_impact.rate_pct}%).
                </p>
              </div>
            </section>

            {campaigns.length > 0 ? (
              <section className="space-y-4">
                <div>
                  <Label>Campaign performance</Label>
                  <p className="mt-1 text-xs text-muted-foreground">
                    Revenue on orders where each campaign was the one applied.
                  </p>
                </div>
                <div className="space-y-4 rounded-2xl border border-border bg-card p-5">
                  {campaigns.map((campaign) => (
                    <BarRow
                      key={campaign.id}
                      label={campaign.description || campaign.id}
                      value={campaign.revenue_inr}
                      max={topCampaignRevenue}
                      tone="mustard"
                      caption={`${rupees(campaign.revenue_inr)} · ${campaign.order_count} order(s) · −${rupees(campaign.discount_inr)}`}
                    />
                  ))}
                </div>
              </section>
            ) : null}

            {topProducts.length > 0 ? (
              <section className="space-y-4">
                <Label>Top products</Label>
                <div className="space-y-4 rounded-2xl border border-border bg-card p-5">
                  {topProducts.map((product) => (
                    <BarRow
                      key={product.product_id}
                      label={product.name}
                      value={product.revenue_inr}
                      max={topProductRevenue}
                      tone="secondary"
                      caption={`${rupees(product.revenue_inr)} · ${product.units} unit(s)`}
                    />
                  ))}
                </div>
              </section>
            ) : null}
          </div>
        )}
      </div>
    </motion.div>
  );
}
