import { cn } from "../lib/utils";

const CIRCUMFERENCE = 2 * Math.PI * 42;

function colorFor(score: number) {
  if (score >= 80) return "var(--color-success)";
  if (score >= 60) return "var(--color-warning)";
  return "var(--color-critical)";
}

export function HealthGauge({ score, size = 128 }: { score: number; size?: number }) {
  const offset = CIRCUMFERENCE - (score / 100) * CIRCUMFERENCE;
  const color = colorFor(score);

  return (
    <div className="relative" style={{ width: size, height: size }}>
      <svg viewBox="0 0 100 100" className="-rotate-90" width={size} height={size}>
        <circle cx="50" cy="50" r="42" fill="none" stroke="var(--color-hairline)" strokeWidth="8" />
        <circle
          cx="50"
          cy="50"
          r="42"
          fill="none"
          stroke={color}
          strokeWidth="8"
          strokeLinecap="round"
          strokeDasharray={CIRCUMFERENCE}
          strokeDashoffset={offset}
          style={{ transition: "stroke-dashoffset 0.8s cubic-bezier(0.4, 0, 0.2, 1)" }}
        />
      </svg>
      <div className="absolute inset-0 flex flex-col items-center justify-center">
        <span className={cn("font-mono-nums font-display text-3xl font-semibold")} style={{ color }}>
          {score}
        </span>
        <span className="text-[10px] uppercase tracking-wider text-fog-2">Health</span>
      </div>
    </div>
  );
}

export function CategoryBar({ label, score, hint }: { label: string; score: number; hint?: string }) {
  const color = colorFor(score);
  return (
    <div className="space-y-1">
      <div className="flex items-center justify-between text-xs">
        <span className="text-fog-1" title={hint}>
          {label}
        </span>
        <span className="font-mono-nums text-fog-0">{score}</span>
      </div>
      {hint && <p className="text-[10px] leading-tight text-fog-2">{hint}</p>}
      <div className="h-1.5 overflow-hidden rounded-full bg-panel-raised">
        <div
          className="h-full rounded-full transition-all duration-700"
          style={{ width: `${score}%`, background: color }}
        />
      </div>
    </div>
  );
}
