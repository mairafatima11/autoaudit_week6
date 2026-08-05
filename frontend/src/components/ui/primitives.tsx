import type { ButtonHTMLAttributes, HTMLAttributes, ReactNode } from "react";
import { cn } from "../../lib/utils";

export function Badge({
  className,
  variant = "neutral",
  ...props
}: HTMLAttributes<HTMLSpanElement> & { variant?: "neutral" | "signal" | "success" | "warning" | "critical" }) {
  const variants: Record<string, string> = {
    neutral: "bg-panel-raised text-fog-1 border-hairline",
    signal: "bg-signal/10 text-signal-glow border-signal-dim",
    success: "bg-success-dim text-success border-success/30",
    warning: "bg-warning-dim text-warning border-warning/30",
    critical: "bg-critical-dim text-critical border-critical/30",
  };
  return (
    <span
      className={cn(
        "inline-flex items-center gap-1 rounded-full border px-2 py-0.5 text-xs font-medium",
        variants[variant],
        className
      )}
      {...props}
    />
  );
}

export function Button({
  className,
  variant = "primary",
  size = "md",
  ...props
}: ButtonHTMLAttributes<HTMLButtonElement> & {
  variant?: "primary" | "secondary" | "ghost" | "danger";
  size?: "sm" | "md";
}) {
  const variants: Record<string, string> = {
    primary: "bg-signal text-ink hover:bg-signal-glow disabled:bg-signal-dim disabled:text-fog-1",
    secondary: "bg-panel-raised text-fog-0 border border-hairline hover:border-fog-2",
    ghost: "text-fog-1 hover:text-fog-0 hover:bg-panel-raised",
    danger: "bg-critical/10 text-critical border border-critical/30 hover:bg-critical/20",
  };
  const sizes: Record<string, string> = {
    sm: "text-xs px-2.5 py-1.5",
    md: "text-sm px-3.5 py-2",
  };
  return (
    <button
      className={cn(
        "inline-flex items-center justify-center gap-1.5 rounded-lg font-medium transition-colors duration-150 disabled:cursor-not-allowed disabled:opacity-60",
        variants[variant],
        sizes[size],
        className
      )}
      {...props}
    />
  );
}

export function EmptyState({
  icon,
  title,
  description,
  action,
}: {
  icon?: ReactNode;
  title: string;
  description?: string;
  action?: ReactNode;
}) {
  return (
    <div className="flex flex-col items-center justify-center gap-3 rounded-xl border border-dashed border-hairline px-6 py-14 text-center">
      {icon && <div className="text-fog-2">{icon}</div>}
      <div className="space-y-1">
        <p className="font-display text-sm font-semibold text-fog-0">{title}</p>
        {description && <p className="max-w-sm text-sm text-fog-2">{description}</p>}
      </div>
      {action}
    </div>
  );
}

export function Skeleton({ className }: { className?: string }) {
  return <div className={cn("animate-pulse rounded-md bg-panel-raised", className)} />;
}
