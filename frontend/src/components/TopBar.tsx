import { Activity } from "lucide-react";
import type { ReactNode } from "react";

export function TopBar({ title, subtitle, right }: { title: string; subtitle?: string; right?: ReactNode }) {
  return (
    <header className="flex items-center justify-between border-b border-hairline bg-ink/80 px-8 py-5 backdrop-blur-sm">
      <div>
        <div className="flex items-center gap-2">
          <Activity size={14} className="text-signal" />
          <h1 className="font-display text-lg font-semibold text-fog-0">{title}</h1>
        </div>
        {subtitle && <p className="mt-0.5 text-sm text-fog-2">{subtitle}</p>}
      </div>
      {right && <div className="flex items-center gap-3">{right}</div>}
    </header>
  );
}
