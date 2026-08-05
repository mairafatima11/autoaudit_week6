import { useMemo, useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { Link } from "react-router-dom";
import { Search, ListChecks, FolderTree, SlidersHorizontal, X } from "lucide-react";
import { TopBar } from "../components/TopBar";
import { Card, CardBody } from "../components/ui/Card";
import { Button, EmptyState, Skeleton } from "../components/ui/primitives";
import { FindingCard } from "../components/FindingCard";
import { SeverityBadge, StatusPill } from "../components/FindingCard";
import { api } from "../lib/api";
import { useRunContext } from "../lib/RunContext";
import type { Finding, FindingCategory, FindingStatus, Severity } from "../lib/types";

const SEVERITIES: Severity[] = ["high", "medium", "low", "info"];
const STATUSES: FindingStatus[] = ["new", "recurring", "fixed"];
// Mirrors the backend `Category` enum exactly. Listing categories no agent
// emits ("documentation", "architecture") gave the user filter options that
// could only ever return zero results, while real `docs` findings had no
// option at all.
const CATEGORIES: FindingCategory[] = ["security", "quality", "docs"];
const CATEGORY_LABELS: Record<FindingCategory, string> = {
  security: "Security",
  quality: "Quality",
  docs: "Documentation",
};

// The pipeline currently routes the Security Agent through Groq and the
// Quality/Documentation Agents through Gemini (see llm/router.py's
// profile_preference) — derived here rather than duplicated as a separate
// backend field, since it's a direct function of source_agent today.
function modelForAgent(agent: string): string {
  if (agent === "security" || agent === "fix") return "Groq";
  if (agent === "quality" || agent === "documentation") return "Gemini";
  return "Unknown";
}

export function FindingsPage() {
  const { activeRunId } = useRunContext();
  const [search, setSearch] = useState("");
  const [severityFilter, setSeverityFilter] = useState<Set<Severity>>(new Set());
  const [agentFilter, setAgentFilter] = useState<string>("all");
  const [modelFilter, setModelFilter] = useState<string>("all");
  const [categoryFilter, setCategoryFilter] = useState<string>("all");
  const [statusFilter, setStatusFilter] = useState<Set<FindingStatus>>(new Set());
  const [pathFilter, setPathFilter] = useState("");
  const [minConfidence, setMinConfidence] = useState(0);
  const [showAdvanced, setShowAdvanced] = useState(false);
  const [selected, setSelected] = useState<Finding | null>(null);

  const auditQuery = useQuery({
    queryKey: ["audit", activeRunId],
    queryFn: () => api.getAudit(activeRunId!),
    enabled: !!activeRunId,
  });

  const findings = auditQuery.data?.report.findings ?? [];
  const agents = useMemo(() => Array.from(new Set(findings.map((f) => f.source_agent))), [findings]);
  const models = useMemo(() => Array.from(new Set(findings.map((f) => modelForAgent(f.source_agent)))), [findings]);

  const filtered = findings.filter((f) => {
    if (severityFilter.size && !severityFilter.has(f.severity)) return false;
    if (statusFilter.size && !statusFilter.has(f.status)) return false;
    if (agentFilter !== "all" && f.source_agent !== agentFilter) return false;
    if (modelFilter !== "all" && modelForAgent(f.source_agent) !== modelFilter) return false;
    if (categoryFilter !== "all" && f.category !== categoryFilter) return false;
    if (pathFilter && !f.file.toLowerCase().includes(pathFilter.toLowerCase())) return false;
    if (f.confidence < minConfidence) return false;
    if (search) {
      const haystack = `${f.title} ${f.description} ${f.file} ${f.rule}`.toLowerCase();
      if (!haystack.includes(search.toLowerCase())) return false;
    }
    return true;
  });

  const activeAdvancedCount =
    (modelFilter !== "all" ? 1 : 0) +
    (categoryFilter !== "all" ? 1 : 0) +
    (statusFilter.size ? 1 : 0) +
    (pathFilter ? 1 : 0) +
    (minConfidence > 0 ? 1 : 0);

  function toggleSet<T>(setter: (updater: (prev: Set<T>) => Set<T>) => void, value: T) {
    setter((prev) => {
      const next = new Set(prev);
      if (next.has(value)) next.delete(value);
      else next.add(value);
      return next;
    });
  }

  function clearAdvanced() {
    setModelFilter("all");
    setCategoryFilter("all");
    setStatusFilter(new Set());
    setPathFilter("");
    setMinConfidence(0);
  }

  if (!activeRunId) {
    return (
      <>
        <TopBar title="Findings" />
        <div className="p-8">
          <EmptyState icon={<ListChecks size={28} />} title="No findings yet" description="Run an audit to see findings here." />
        </div>
      </>
    );
  }

  return (
    <>
      <TopBar title="Findings" subtitle={`${filtered.length} of ${findings.length} findings`} />
      <div className="grid grid-cols-1 gap-6 p-8 lg:grid-cols-5">
        <div className="space-y-4 lg:col-span-2">
          <div className="relative">
            <Search size={15} className="absolute left-3 top-1/2 -translate-y-1/2 text-fog-2" />
            <input
              value={search}
              onChange={(e) => setSearch(e.target.value)}
              placeholder="Search findings…"
              className="w-full rounded-lg border border-hairline bg-panel py-2 pl-9 pr-3 text-sm text-fog-0 placeholder:text-fog-2 focus:border-signal"
            />
          </div>

          <div className="flex flex-wrap items-center gap-2">
            {SEVERITIES.map((s) => (
              <button
                key={s}
                onClick={() => toggleSet(setSeverityFilter, s)}
                className={`rounded-full border px-2.5 py-1 text-xs font-medium transition-colors ${
                  severityFilter.has(s)
                    ? "border-signal bg-signal/10 text-signal-glow"
                    : "border-hairline text-fog-2 hover:text-fog-0"
                }`}
              >
                {s}
              </button>
            ))}
            <select
              value={agentFilter}
              onChange={(e) => setAgentFilter(e.target.value)}
              className="rounded-full border border-hairline bg-panel px-2.5 py-1 text-xs text-fog-1"
            >
              <option value="all">All agents</option>
              {agents.map((a) => (
                <option key={a} value={a}>
                  {a}
                </option>
              ))}
            </select>
            <button
              onClick={() => setShowAdvanced((v) => !v)}
              className={`ml-auto flex items-center gap-1.5 rounded-full border px-2.5 py-1 text-xs font-medium transition-colors ${
                showAdvanced || activeAdvancedCount > 0
                  ? "border-signal bg-signal/10 text-signal-glow"
                  : "border-hairline text-fog-2 hover:text-fog-0"
              }`}
            >
              <SlidersHorizontal size={12} /> More filters
              {activeAdvancedCount > 0 && <span className="font-mono-nums">({activeAdvancedCount})</span>}
            </button>
          </div>

          {showAdvanced && (
            <Card>
              <CardBody className="space-y-3 pt-4">
                <div className="flex items-center justify-between">
                  <p className="text-xs font-medium uppercase tracking-wider text-fog-2">Advanced Filters</p>
                  {activeAdvancedCount > 0 && (
                    <button onClick={clearAdvanced} className="flex items-center gap-1 text-xs text-fog-2 hover:text-fog-0">
                      <X size={11} /> Clear
                    </button>
                  )}
                </div>

                <div className="grid grid-cols-2 gap-3">
                  <div>
                    <label className="mb-1 block text-[11px] text-fog-2">AI Model</label>
                    <select
                      value={modelFilter}
                      onChange={(e) => setModelFilter(e.target.value)}
                      className="w-full rounded-lg border border-hairline bg-panel-raised px-2 py-1.5 text-xs text-fog-1"
                    >
                      <option value="all">All models</option>
                      {models.map((m) => (
                        <option key={m} value={m}>
                          {m}
                        </option>
                      ))}
                    </select>
                  </div>
                  <div>
                    <label className="mb-1 block text-[11px] text-fog-2">Finding Type</label>
                    <select
                      value={categoryFilter}
                      onChange={(e) => setCategoryFilter(e.target.value)}
                      className="w-full rounded-lg border border-hairline bg-panel-raised px-2 py-1.5 text-xs text-fog-1"
                    >
                      <option value="all">All types</option>
                      {CATEGORIES.map((c) => (
                        <option key={c} value={c}>
                          {CATEGORY_LABELS[c]}
                        </option>
                      ))}
                    </select>
                  </div>
                </div>

                <div>
                  <label className="mb-1 block text-[11px] text-fog-2">File / folder path contains</label>
                  <input
                    value={pathFilter}
                    onChange={(e) => setPathFilter(e.target.value)}
                    placeholder="e.g. src/auth/"
                    className="w-full rounded-lg border border-hairline bg-panel-raised px-2 py-1.5 text-xs text-fog-0 placeholder:text-fog-2"
                  />
                </div>

                <div>
                  <label className="mb-1 flex items-center justify-between text-[11px] text-fog-2">
                    <span>Minimum confidence</span>
                    <span className="font-mono-nums">{Math.round(minConfidence * 100)}%</span>
                  </label>
                  <input
                    type="range"
                    min={0}
                    max={1}
                    step={0.05}
                    value={minConfidence}
                    onChange={(e) => setMinConfidence(Number(e.target.value))}
                    className="w-full accent-signal"
                  />
                </div>

                <div>
                  <label className="mb-1 block text-[11px] text-fog-2">Status</label>
                  <div className="flex flex-wrap gap-1.5">
                    {STATUSES.map((s) => (
                      <button
                        key={s}
                        onClick={() => toggleSet(setStatusFilter, s)}
                        className={`rounded-full border px-2 py-0.5 text-[11px] font-medium transition-colors ${
                          statusFilter.has(s)
                            ? "border-signal bg-signal/10 text-signal-glow"
                            : "border-hairline text-fog-2 hover:text-fog-0"
                        }`}
                      >
                        {s}
                      </button>
                    ))}
                  </div>
                </div>
              </CardBody>
            </Card>
          )}

          <div className="max-h-[calc(100vh-260px)] space-y-2 overflow-y-auto pr-1">
            {auditQuery.isLoading && <Skeleton className="h-16 w-full" />}
            {filtered.map((f) => (
              <FindingCard key={f.fingerprint} finding={f} onSelect={setSelected} />
            ))}
            {!auditQuery.isLoading && filtered.length === 0 && (
              <p className="py-8 text-center text-sm text-fog-2">No findings match your filters.</p>
            )}
          </div>
        </div>

        <div className="lg:col-span-3">
          {selected ? (
            <Card>
              <CardBody className="space-y-4 pt-5">
                <div className="flex items-center gap-2">
                  <SeverityBadge severity={selected.severity} />
                  <StatusPill status={selected.status} />
                  <span className="rounded-full bg-panel-raised px-2 py-0.5 text-[11px] text-fog-2">
                    {modelForAgent(selected.source_agent)} · {Math.round(selected.confidence * 100)}% confidence
                  </span>
                </div>
                <h2 className="font-display text-lg font-semibold text-fog-0">{selected.title}</h2>
                <p className="font-mono-nums text-xs text-fog-2">
                  {selected.file}:{selected.line} · rule: {selected.rule} · via {selected.source_agent} ({selected.source_tool})
                </p>
                <Link to={`/explorer?file=${encodeURIComponent(selected.file)}&line=${selected.line}`}>
                  <Button size="sm" variant="secondary">
                    <FolderTree size={13} /> View in Explorer
                  </Button>
                </Link>
                <p className="text-sm leading-relaxed text-fog-1">{selected.description}</p>
                {selected.evidence && (
                  <div>
                    <p className="mb-1.5 text-xs font-medium uppercase tracking-wider text-fog-2">Evidence</p>
                    <pre className="overflow-x-auto rounded-lg border border-hairline-soft bg-ink p-3 font-mono-nums text-xs text-fog-1">
                      {selected.evidence}
                    </pre>
                  </div>
                )}
              </CardBody>
            </Card>
          ) : (
            <EmptyState title="Select a finding" description="Choose a finding from the list to see evidence and details." />
          )}
        </div>
      </div>
    </>
  );
}
