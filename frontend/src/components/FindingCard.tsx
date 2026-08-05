import { ChevronRight } from "lucide-react";
import { SEVERITY_META, cn } from "../lib/utils";
import type { Finding } from "../lib/types";

export function SeverityBadge({ severity }: { severity: Finding["severity"] }) {
  const meta = SEVERITY_META[severity];
  return (
    <span className={cn("inline-flex items-center gap-1.5 rounded-full px-2 py-0.5 text-xs font-medium", meta.dim, meta.color)}>
      <span className={cn("h-1.5 w-1.5 rounded-full", meta.dot)} />
      {meta.label}
    </span>
  );
}

export function StatusPill({ status }: { status: Finding["status"] }) {
  const map: Record<Finding["status"], { label: string; className: string }> = {
    new: { label: "New", className: "bg-signal/10 text-signal-glow" },
    recurring: { label: "Recurring", className: "bg-warning-dim text-warning" },
    fixed: { label: "Fixed", className: "bg-success-dim text-success" },
  };
  const { label, className } = map[status];
  return <span className={cn("rounded-full px-2 py-0.5 text-xs font-medium", className)}>{label}</span>;
}

export function FindingCard({ finding, onSelect }: { finding: Finding; onSelect?: (f: Finding) => void }) {
  return (
    <button
      onClick={() => onSelect?.(finding)}
      className="group flex w-full items-center justify-between gap-4 rounded-lg border border-hairline bg-panel px-4 py-3 text-left transition-colors hover:border-fog-2 hover:bg-panel-raised"
    >
      <div className="min-w-0 flex-1 space-y-1.5">
        <div className="flex items-center gap-2">
          <SeverityBadge severity={finding.severity} />
          <StatusPill status={finding.status} />
          <span className="rounded-full bg-panel-raised px-2 py-0.5 text-[11px] text-fog-2">{finding.source_agent}</span>
        </div>
        <p className="truncate text-sm font-medium text-fog-0">{finding.title}</p>
        <p className="font-mono-nums truncate text-xs text-fog-2">
          {finding.file}:{finding.line} · {finding.rule}
        </p>
      </div>
      <ChevronRight size={16} className="shrink-0 text-fog-2 transition-transform group-hover:translate-x-0.5" />
    </button>
  );
}
