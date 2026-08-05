import { motion } from "framer-motion";
import { Check, X, Loader2 } from "lucide-react";
import { cn } from "../lib/utils";
import type { AgentStageStatus, PipelineStage } from "../lib/types";

const AGENT_LABELS: Record<string, string> = {
  supervisor: "Supervisor",
  repository_agent: "Repository",
  security_agent: "Security",
  quality_agent: "Quality",
  documentation_agent: "Docs",
  fix_agent: "Fix",
  report_agent: "Report",
};

const DEFAULT_STAGES: PipelineStage[] = [
  { agent: "supervisor", status: "pending", duration_seconds: null, current_file: null },
  { agent: "repository_agent", status: "pending", duration_seconds: null, current_file: null },
  { agent: "security_agent", status: "pending", duration_seconds: null, current_file: null },
  { agent: "quality_agent", status: "pending", duration_seconds: null, current_file: null },
  { agent: "documentation_agent", status: "pending", duration_seconds: null, current_file: null },
  { agent: "report_agent", status: "pending", duration_seconds: null, current_file: null },
];

function NodeVisual({ status, size }: { status: AgentStageStatus; size: "sm" | "lg" }) {
  const dims = size === "lg" ? "h-11 w-11" : "h-6 w-6";
  const iconSize = size === "lg" ? 18 : 12;

  if (status === "completed") {
    return (
      <div className={cn(dims, "flex items-center justify-center rounded-full border-2 border-success bg-success-dim")}>
        <Check size={iconSize} className="text-success" strokeWidth={2.5} />
      </div>
    );
  }
  if (status === "running") {
    return (
      <div
        className={cn(
          dims,
          "flex items-center justify-center rounded-full border-2 border-signal bg-signal/10"
        )}
        style={{ animation: "pulse-ring 1.6s ease-out infinite" }}
      >
        <Loader2 size={iconSize} className="animate-spin text-signal" />
      </div>
    );
  }
  if (status === "error") {
    return (
      <div className={cn(dims, "flex items-center justify-center rounded-full border-2 border-critical bg-critical-dim")}>
        <X size={iconSize} className="text-critical" strokeWidth={2.5} />
      </div>
    );
  }
  return <div className={cn(dims, "rounded-full border-2 border-hairline bg-panel-raised")} />;
}

export function PipelineRail({
  stages = DEFAULT_STAGES,
  size = "lg",
  showLabels = true,
}: {
  stages?: PipelineStage[];
  size?: "sm" | "lg";
  showLabels?: boolean;
}) {
  const isRunning = stages.some((s) => s.status === "running");

  return (
    <div className="w-full overflow-x-auto">
      <div className="flex min-w-max items-center gap-0 py-2">
        {stages.map((stage, i) => (
          <div key={stage.agent} className="flex items-center">
            <div className="flex flex-col items-center gap-2">
              <NodeVisual status={stage.status} size={size} />
              {showLabels && (
                <span
                  className={cn(
                    "font-mono-nums text-[11px] uppercase tracking-wider",
                    stage.status === "completed" && "text-success",
                    stage.status === "running" && "text-signal-glow",
                    stage.status === "error" && "text-critical",
                    stage.status === "pending" && "text-fog-2"
                  )}
                >
                  {AGENT_LABELS[stage.agent] ?? stage.agent}
                </span>
              )}
              {size === "lg" && showLabels && (stage.duration_seconds !== null || stage.current_file) && (
                <div className="flex max-w-[7rem] flex-col items-center gap-0.5 text-center">
                  {stage.duration_seconds !== null && (
                    <span className="font-mono-nums text-[10px] text-fog-2">{stage.duration_seconds.toFixed(1)}s</span>
                  )}
                  {stage.current_file && (
                    <span className="truncate text-[10px] text-fog-2" title={stage.current_file}>
                      {stage.current_file}
                    </span>
                  )}
                </div>
              )}
            </div>
            {i < stages.length - 1 && (
              <div
                className={cn(
                  "relative mx-1 h-[2px] overflow-hidden rounded-full",
                  size === "lg" ? "w-14" : "w-8",
                  stages[i + 1].status !== "pending" || stage.status === "completed"
                    ? "bg-success/40"
                    : "bg-hairline"
                )}
                style={{ marginBottom: showLabels ? "1.15rem" : 0 }}
              >
                {isRunning && stage.status === "running" && (
                  <motion.div
                    className="absolute inset-y-0 w-1/2 bg-gradient-to-r from-transparent via-signal-glow to-transparent"
                    style={{ animation: "scan-beam 1.4s linear infinite" }}
                  />
                )}
              </div>
            )}
          </div>
        ))}
      </div>
    </div>
  );
}
