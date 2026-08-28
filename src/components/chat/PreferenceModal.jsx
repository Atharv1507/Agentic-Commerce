import { useState } from "react";
import { motion } from "framer-motion";
import { X } from "lucide-react";
import { Button } from "@/components/ui/button";
import { cn } from "@/lib/utils";

// Shown when the agent needs to narrow a vague request ("some shirts") before
// searching. Every field is optional and the whole thing can be dismissed —
// the point is to remove ambiguity when the shopper is willing to give it, not
// to gate the search behind a questionnaire.
export default function PreferenceModal({ form, onSubmit, onSkipAll }) {
  const [answers, setAnswers] = useState({});

  const toggle = (field, option) => {
    setAnswers((prev) => {
      const current = prev[field.key] || [];
      if (!field.multiple) {
        // Single-select behaves like a radio you can also clear.
        return { ...prev, [field.key]: current[0] === option ? [] : [option] };
      }
      return {
        ...prev,
        [field.key]: current.includes(option)
          ? current.filter((o) => o !== option)
          : [...current, option],
      };
    });
  };

  const clearField = (key) => setAnswers((prev) => ({ ...prev, [key]: [] }));

  const answeredCount = Object.values(answers).filter((v) => v?.length).length;

  const labelFor = (option) => (typeof option === "string" ? option : option.label);

  return (
    <motion.div
      className="flex w-full justify-start"
      initial={{ opacity: 0, y: 8 }}
      animate={{ opacity: 1, y: 0 }}
    >
      <div className="w-full max-w-xl overflow-hidden rounded-2xl rounded-bl-md border border-primary/15 bg-card">
        <div className="flex items-start gap-3 border-b border-border px-5 py-4">
          <div className="min-w-0 flex-1">
            <h3 className="text-sm font-semibold">{form.title}</h3>
            <p className="mt-0.5 text-xs text-muted-foreground">{form.subtitle}</p>
          </div>
          <button
            onClick={onSkipAll}
            className="shrink-0 rounded-lg p-1.5 text-muted-foreground transition-colors hover:bg-secondary hover:text-foreground"
            aria-label="Skip all questions and search anyway"
            title="Skip all"
          >
            <X className="size-4" />
          </button>
        </div>

        <div className="flex flex-col gap-4 px-5 py-4">
          {form.fields.map((field) => {
            const selected = answers[field.key] || [];
            return (
              <div key={field.key} className="flex flex-col gap-2">
                <div className="flex items-center justify-between gap-2">
                  <p className="text-xs font-medium text-muted-foreground">{field.question}</p>
                  {selected.length > 0 && (
                    <button
                      onClick={() => clearField(field.key)}
                      className="text-xs text-muted-foreground/70 underline-offset-2 hover:text-foreground hover:underline"
                    >
                      Clear
                    </button>
                  )}
                </div>
                <div className="flex flex-wrap gap-1.5">
                  {field.options.map((option) => {
                    const label = labelFor(option);
                    const isOn = selected.includes(label);
                    return (
                      <button
                        key={label}
                        onClick={() => toggle(field, label)}
                        aria-pressed={isOn}
                        className={cn(
                          "rounded-full border px-3 py-1.5 text-xs capitalize transition-colors",
                          isOn
                            ? "border-primary bg-primary text-primary-foreground"
                            : "border-border bg-secondary/40 text-muted-foreground hover:border-primary/40 hover:text-foreground"
                        )}
                      >
                        {label}
                      </button>
                    );
                  })}
                </div>
              </div>
            );
          })}
        </div>

        <div className="flex items-center justify-end gap-2 border-t border-border px-5 py-3">
          <Button variant="ghost" size="sm" onClick={onSkipAll}>
            Skip &amp; show me anything
          </Button>
          <Button size="sm" onClick={() => onSubmit(answers)} disabled={answeredCount === 0}>
            {answeredCount === 0 ? "Pick any to continue" : `Search with ${answeredCount}`}
          </Button>
        </div>
      </div>
    </motion.div>
  );
}
