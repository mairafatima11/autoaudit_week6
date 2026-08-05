import { useEffect, useState } from "react";
import { AlertTriangle, Loader2 } from "lucide-react";

/**
 * Long-running work indicator that shows elapsed time.
 *
 * A bare spinner with static text ("Fix Agent is drafting proposals…") is
 * indistinguishable from a hang: after thirty seconds the user has no way to
 * tell whether the request is progressing, stuck, or already dead. Showing
 * the clock — and warning once the wait becomes unusual — makes the
 * difference visible without needing real server-side progress events.
 */
export function PendingWork({
  label,
  expectedSeconds = 30,
  timeoutSeconds,
}: {
  label: string;
  /** Past this, the wait is flagged as longer than normal. */
  expectedSeconds?: number;
  /** When the client gives up, so the user knows there's a bound. */
  timeoutSeconds?: number;
}) {
  const [elapsed, setElapsed] = useState(0);

  useEffect(() => {
    const started = Date.now();
    const id = setInterval(() => setElapsed(Math.floor((Date.now() - started) / 1000)), 1000);
    return () => clearInterval(id);
  }, []);

  const slow = elapsed > expectedSeconds;

  return (
    <div className="space-y-2">
      <div className="flex items-center gap-2 text-sm text-fog-1">
        <Loader2 size={14} className="animate-spin text-signal" />
        <span>{label}</span>
        <span className="font-mono-nums text-xs text-fog-2">{elapsed}s</span>
      </div>
      <div className="h-1 w-full overflow-hidden rounded-full bg-panel-raised">
        <div
          className="h-full rounded-full bg-signal transition-all duration-1000"
          style={{
            width: `${Math.min(100, (elapsed / (timeoutSeconds ?? expectedSeconds * 2)) * 100)}%`,
          }}
        />
      </div>
      {slow && (
        <p className="flex items-start gap-1.5 text-xs text-warning">
          <AlertTriangle size={12} className="mt-0.5 shrink-0" />
          <span>
            Taking longer than usual — a model provider may be rate-limiting or degraded.
            {timeoutSeconds ? ` This will stop automatically after ${timeoutSeconds}s.` : ""}
          </span>
        </p>
      )}
    </div>
  );
}
