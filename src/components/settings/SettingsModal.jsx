import { useCallback, useEffect, useState } from "react";
import {
  Dialog,
  DialogContent,
  DialogHeader,
  DialogTitle,
  DialogDescription,
  DialogFooter,
} from "@/components/ui/dialog";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { cn } from "@/lib/utils";

const API_BASE = import.meta.env.VITE_API_BASE_URL || "http://localhost:8000";

const GENDER_OPTIONS = ["Male", "Female", "Other"];
const PAYMENT_OPTIONS = ["UPI", "Card", "COD"];
const SIZE_OPTIONS = ["XS", "S", "M", "L", "XL", "XXL"];

// How each saved preference reads back to the shopper. Fabric is absent on
// purpose: it belongs to a product type, not to a person, so it is never saved
// account-wide (a fabric mentioned once used to filter every later search).
const PREFERENCE_LABELS = {
  colors: "Colours",
  brands: "Brands",
  categories: "Categories",
  style: "Style",
  budget_level: "Spend level",
  avoid: "Avoids",
};

function OptionPills({ options, value, onChange }) {
  return (
    <div className="flex gap-2">
      {options.map((option) => (
        <button
          key={option}
          type="button"
          onClick={() => onChange(option)}
          className={cn(
            "flex-1 rounded-lg border px-3 py-2 text-sm transition-colors",
            value === option ? "border-primary bg-primary/10 text-foreground" : "border-border text-muted-foreground hover:border-primary/50"
          )}
        >
          {option}
        </button>
      ))}
    </div>
  );
}

function FieldLabel({ children }) {
  return (
    <label className="mb-1.5 block text-xs tracking-wide text-muted-foreground uppercase">{children}</label>
  );
}

// Anything that silently shapes results has to be visible and removable, so
// preferences the agent picked up in conversation are listed here as chips the
// shopper can delete one at a time.
function PreferenceEditor({ email }) {
  const [preferences, setPreferences] = useState(null);
  const [busy, setBusy] = useState(false);

  useEffect(() => {
    if (!email) return;
    let active = true;
    fetch(`${API_BASE}/session/${email}/preferences`)
      .then((res) => (res.ok ? res.json() : { preferences: {} }))
      .then((data) => active && setPreferences(data.preferences || {}))
      .catch(() => active && setPreferences({}));
    return () => {
      active = false;
    };
  }, [email]);

  const persist = useCallback(
    async (next) => {
      setPreferences(next);
      setBusy(true);
      try {
        await fetch(`${API_BASE}/session/${email}/preferences`, {
          method: "PUT",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ preferences: next }),
        });
      } catch {
        // Best effort — the chips already reflect the intent locally.
      }
      setBusy(false);
    },
    [email]
  );

  const removeValue = (field, value) => {
    const current = preferences[field];
    const next = { ...preferences };
    if (Array.isArray(current)) {
      const remaining = current.filter((v) => v !== value);
      if (remaining.length) next[field] = remaining;
      else delete next[field];
    } else {
      delete next[field];
    }
    persist(next);
  };

  if (preferences === null) {
    return <p className="text-sm text-muted-foreground">Loading your preferences…</p>;
  }

  const entries = Object.entries(preferences).filter(([, value]) =>
    Array.isArray(value) ? value.length : Boolean(value)
  );

  if (!entries.length) {
    return (
      <p className="text-sm text-muted-foreground">
        Nothing saved yet. Lasting tastes you mention in chat — “I always wear black”, “I'm a Nike
        person” — show up here, and what you ask for in a single conversation stays in that
        conversation.
      </p>
    );
  }

  return (
    <div className="flex flex-col gap-3">
      {entries.map(([field, value]) => (
        <div key={field}>
          <FieldLabel>{PREFERENCE_LABELS[field] || field}</FieldLabel>
          <div className="flex flex-wrap gap-2">
            {(Array.isArray(value) ? value : [value]).map((item) => (
              <button
                key={`${field}-${item}`}
                type="button"
                disabled={busy}
                onClick={() => removeValue(field, item)}
                title="Remove this preference"
                className="group flex items-center gap-1.5 rounded-full border border-border px-3 py-1 text-sm text-foreground transition-colors hover:border-destructive/60 hover:text-destructive disabled:opacity-50"
              >
                {item}
                <span className="text-muted-foreground group-hover:text-destructive">×</span>
              </button>
            ))}
          </div>
        </div>
      ))}

      <button
        type="button"
        disabled={busy}
        onClick={() => persist({})}
        className="self-start text-xs text-muted-foreground underline underline-offset-4 hover:text-destructive disabled:opacity-50"
      >
        Clear all preferences
      </button>
    </div>
  );
}

// Keyed by `open` in the parent so this remounts fresh from `session` each time
// the dialog opens, instead of syncing props into state via an effect.
function SettingsForm({ session, onOpenChange, onSave }) {
  const [values, setValues] = useState({
    name: session?.name || "",
    phone: session?.phone || "",
    address: session?.address || "",
    gender: session?.gender || "Other",
    size: session?.size || "",
    payment_method: session?.paymentMethod || "COD",
    spend_limit: session?.spendLimit || 5000,
  });
  const [saving, setSaving] = useState(false);

  const set = (key) => (e) => setValues((prev) => ({ ...prev, [key]: e.target.value }));

  const handleSave = async () => {
    setSaving(true);
    await onSave(values);
    setSaving(false);
    onOpenChange(false);
  };

  return (
    <>
      <div className="flex max-h-[60vh] flex-col gap-6 overflow-y-auto pr-1">
        <section className="flex flex-col gap-4">
          <div>
            <h3 className="text-sm font-medium text-foreground">Your details</h3>
            <p className="text-xs text-muted-foreground">
              Used for delivery and checkout. Gender and size also filter what your agent shows
              you — it only surfaces items actually in stock in your size.
            </p>
          </div>

          <div>
            <FieldLabel>Email</FieldLabel>
            <Input value={session?.email || ""} disabled />
          </div>
          <div>
            <FieldLabel>Name</FieldLabel>
            <Input value={values.name} onChange={set("name")} placeholder="Your name" />
          </div>
          <div>
            <FieldLabel>Phone</FieldLabel>
            <Input value={values.phone} onChange={set("phone")} placeholder="9876543210" />
          </div>
          <div>
            <FieldLabel>Delivery address</FieldLabel>
            <Input value={values.address} onChange={set("address")} placeholder="Your address" />
          </div>
          <div>
            <FieldLabel>Gender</FieldLabel>
            <OptionPills
              options={GENDER_OPTIONS}
              value={values.gender}
              onChange={(v) => setValues((prev) => ({ ...prev, gender: v }))}
            />
          </div>
          <div>
            <FieldLabel>Size</FieldLabel>
            <OptionPills
              options={SIZE_OPTIONS}
              value={values.size}
              onChange={(v) => setValues((prev) => ({ ...prev, size: prev.size === v ? "" : v }))}
            />
            <p className="mt-1.5 text-xs text-muted-foreground">
              {values.size
                ? `Only shirts in stock in ${values.size} will be shown.`
                : "Not set — you'll be shown items that may not come in your size."}
            </p>
          </div>
          <div>
            <FieldLabel>Payment method</FieldLabel>
            <OptionPills
              options={PAYMENT_OPTIONS}
              value={values.payment_method}
              onChange={(v) => setValues((prev) => ({ ...prev, payment_method: v }))}
            />
          </div>
        </section>

        <section className="flex flex-col gap-3 border-t border-border pt-5">
          <div>
            <h3 className="text-sm font-medium text-foreground">Spend limit</h3>
            <p className="text-xs text-muted-foreground">
              Orders above this amount need your explicit confirmation in a popup before payment
              starts. This can only be changed here, never in chat.
            </p>
          </div>
          <div>
            <FieldLabel>Auto-approve up to (₹)</FieldLabel>
            <Input
              type="number"
              min={0}
              value={values.spend_limit}
              onChange={(e) =>
                setValues((prev) => ({ ...prev, spend_limit: Number(e.target.value) || 0 }))
              }
              placeholder="5000"
            />
          </div>
        </section>

        <section className="flex flex-col gap-3 border-t border-border pt-5">
          <div>
            <h3 className="text-sm font-medium text-foreground">Shopping preferences</h3>
            <p className="text-xs text-muted-foreground">
              Lasting tastes your agent applies as a soft default. Removing one takes effect on your
              next search.
            </p>
          </div>
          <PreferenceEditor email={session?.email} />
        </section>
      </div>

      <DialogFooter>
        <Button variant="outline" onClick={() => onOpenChange(false)}>
          Cancel
        </Button>
        <Button onClick={handleSave} disabled={saving}>
          {saving ? "Saving..." : "Save changes"}
        </Button>
      </DialogFooter>
    </>
  );
}

export default function SettingsModal({ open, onOpenChange, session, onSave }) {
  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className="border-border bg-card text-card-foreground sm:max-w-md">
        <DialogHeader>
          <DialogTitle className="font-hero text-xl font-medium">Settings</DialogTitle>
          <DialogDescription>Your details and the preferences your agent remembers.</DialogDescription>
        </DialogHeader>

        <SettingsForm key={open} session={session} onOpenChange={onOpenChange} onSave={onSave} />
      </DialogContent>
    </Dialog>
  );
}
