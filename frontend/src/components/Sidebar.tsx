import { NavLink } from "react-router-dom";
import {
  LayoutDashboard,
  FolderGit2,
  ScanSearch,
  FolderTree,
  ListChecks,
  Wrench,
  Split,
  Database,
  FileOutput,
  
} from "lucide-react";
import { cn } from "../lib/utils";

const NAV = [
  { to: "/", label: "Dashboard", icon: LayoutDashboard, end: true },
  { to: "/repository", label: "Repository", icon: FolderGit2 },
  { to: "/audit", label: "Audit", icon: ScanSearch },
  { to: "/explorer", label: "Explorer", icon: FolderTree },
  { to: "/findings", label: "Findings", icon: ListChecks },
  { to: "/fixes", label: "Fixes", icon: Wrench },
  { to: "/ai-comparison", label: "AI Comparison", icon: Split },
  { to: "/memory", label: "Memory", icon: Database },
  { to: "/reports", label: "Reports", icon: FileOutput },
];

export function Sidebar() {
  return (
    <aside className="flex h-full w-[220px] shrink-0 flex-col border-r border-hairline bg-panel/60">
      <div className="flex items-center gap-2.5 px-5 py-5">
        <div className="relative h-7 w-7 shrink-0 rounded-md border border-hairline bg-panel-raised">
          <span className="absolute left-1 top-1/2 h-1.5 w-1.5 -translate-y-1/2 rounded-full bg-signal" />
          <span className="absolute right-1 top-1/2 h-1.5 w-1.5 -translate-y-1/2 rounded-full bg-success" />
        </div>
        <div className="leading-tight">
          <p className="font-display text-[13px] font-semibold text-fog-0">AutoAudit AI</p>
          <p className="text-[10px] uppercase tracking-wider text-fog-2">Reviewer</p>
        </div>
      </div>

      <nav className="flex flex-1 flex-col gap-0.5 px-3">
        {NAV.map(({ to, label, icon: Icon, end }) => (
          <NavLink
            key={to}
            to={to}
            end={end}
            className={({ isActive }) =>
              cn(
                "flex items-center gap-2.5 rounded-lg px-3 py-2 text-sm font-medium transition-colors",
                isActive
                  ? "bg-signal/10 text-signal-glow"
                  : "text-fog-1 hover:bg-panel-raised hover:text-fog-0"
              )
            }
          >
            <Icon size={16} strokeWidth={2} />
            {label}
          </NavLink>
        ))}
      </nav>
    </aside>
  );
}
