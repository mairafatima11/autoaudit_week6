import type { LucideIcon } from "lucide-react";
import { Card } from "./ui/Card";
import { cn } from "../lib/utils";

export function StatCard({
  label,
  value,
  icon: Icon,
  tone = "neutral",
  trend,
}: {
  label: string;
  value: string | number;
  icon?: LucideIcon;
  tone?: "neutral" | "critical" | "warning" | "success" | "signal";
  trend?: string;
}) {
  const toneClass: Record<string, string> = {
    neutral: "text-fog-0",
    critical: "text-critical",
    warning: "text-warning",
    success: "text-success",
    signal: "text-signal-glow",
  };
  return (
    <Card className="px-4 py-4">
      <div className="flex items-start justify-between">
        <p className="text-xs font-medium uppercase tracking-wider text-fog-2">{label}</p>
        {Icon && <Icon size={15} className="text-fog-2" />}
      </div>
      <p className={cn("font-mono-nums font-display mt-2 text-2xl font-semibold", toneClass[tone])}>{value}</p>
      {trend && <p className="mt-1 text-xs text-fog-2">{trend}</p>}
    </Card>
  );
}
