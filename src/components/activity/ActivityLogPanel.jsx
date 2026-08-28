import { useState } from "react";
import { ChevronDown, ChevronRight } from "lucide-react";
import {
  Dialog,
  DialogContent,
  DialogHeader,
  DialogTitle,
  DialogDescription,
} from "@/components/ui/dialog";
import { cn } from "@/lib/utils";
import useActivityLog from "@/hooks/useActivityLog";

function ActivityRow({ entry }) {
  const [expanded, setExpanded] = useState(false);
  const time = entry.timestamp ? new Date(entry.timestamp * 1000).toLocaleString() : "";

  return (
    <div className="rounded-xl border border-border bg-card/40 p-3 backdrop-blur-sm">
      <button
        type="button"
        onClick={() => setExpanded((v) => !v)}
        className="flex w-full items-start gap-2 text-left"
      >
        {expanded ? (
          <ChevronDown className="mt-0.5 size-3.5 shrink-0 text-muted-foreground" />
        ) : (
          <ChevronRight className="mt-0.5 size-3.5 shrink-0 text-muted-foreground" />
        )}
        <div className="min-w-0 flex-1">
          <div className="flex items-center justify-between gap-2">
            <span className="text-xs tracking-widest text-muted-foreground/70 uppercase">
              {entry.tool}
            </span>
            <span className="shrink-0 text-xs text-muted-foreground">{time}</span>
          </div>
          <p className="mt-0.5 text-sm text-foreground">{entry.summary}</p>
        </div>
      </button>

      {expanded && (
        <pre className="mt-3 max-h-56 overflow-auto rounded-lg bg-background/60 p-2.5 text-xs whitespace-pre-wrap text-muted-foreground">
          {JSON.stringify({ input: entry.input, output: entry.output }, null, 2)}
        </pre>
      )}
    </div>
  );
}

function ActivityList({ session }) {
  const { entries } = useActivityLog(session, true);

  if (entries === null) {
    return <p className="text-sm text-muted-foreground">Loading activity…</p>;
  }

  if (!entries.length) {
    return (
      <p className="text-sm text-muted-foreground">
        No activity yet. Every tool call your agent makes — searches, cart changes, checkout,
        payments — shows up here as it happens.
      </p>
    );
  }

  return (
    <div className="flex flex-col gap-2">
      {entries.map((entry, i) => (
        <ActivityRow key={`${entry.timestamp}-${i}`} entry={entry} />
      ))}
    </div>
  );
}

// The audit trail: a per-shopper, chronological record of every tool call the
// agent made, pulled fresh from GET /session/{email}/logs each time this
// opens. Built on the Dialog primitive to match SettingsModal — this is a
// read-only informational panel, so a centered modal fits it as well as a
// side drawer would, and there's no drawer/sheet primitive already in the repo.
export default function ActivityLogPanel({ open, onOpenChange, session }) {
  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className={cn("border-border bg-card text-card-foreground sm:max-w-lg")}>
        <DialogHeader>
          <DialogTitle className="font-hero text-xl font-medium">Activity log</DialogTitle>
          <DialogDescription>
            Every action your agent has taken in this account — the audit trail behind its
            decisions.
          </DialogDescription>
        </DialogHeader>

        <div className="max-h-[60vh] overflow-y-auto pr-1">
          <ActivityList key={open} session={session} />
        </div>
      </DialogContent>
    </Dialog>
  );
}
