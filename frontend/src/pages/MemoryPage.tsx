import { useEffect, useMemo, useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { Database, GitCompare, Repeat, Search } from "lucide-react";
import {
  LineChart,
  Line,
  BarChart,
  Bar,
  XAxis,
  YAxis,
  CartesianGrid,
  Tooltip,
  Legend,
  ResponsiveContainer,
} from "recharts";
import { TopBar } from "../components/TopBar";
import { Card, CardBody, CardHeader, CardTitle } from "../components/ui/Card";
import { Badge, Button, EmptyState, Skeleton } from "../components/ui/primitives";
import { SeverityBadge } from "../components/FindingCard";
import { api } from "../lib/api";
import { formatTimestamp, shortRepoName } from "../lib/utils";

const SEVERITY_LINE_COLOR: Record<string, string> = {
  high: "var(--color-critical)",
  medium: "var(--color-warning)",
  low: "var(--color-caution)",
  info: "var(--color-info)",
};

const chartTooltipStyle = {
  background: "var(--color-panel-raised)",
  border: "1px solid var(--color-hairline)",
  borderRadius: 8,
  fontSize: 12,
};

export function MemoryPage() {
  // Trends are only meaningful *within* a repository. This page used to chart
  // every run in the database on one line regardless of which repo it came
  // from, so a large project and a two-file toy repo sat side by side and the
  // "health score trend" was really just repo-to-repo variance.
  const reposQuery = useQuery({ queryKey: ["repositories"], queryFn: api.listRepositories });
  // Memoised so the default-selection effect below doesn't re-run on every
  // render (a fresh `[]` literal would be a new identity each time).
  const repositories = useMemo(() => reposQuery.data?.repositories ?? [], [reposQuery.data]);
  const [repoId, setRepoId] = useState<string>("");

  useEffect(() => {
    if (!repoId && repositories.length) setRepoId(repositories[0].repo_id);
  }, [repositories, repoId]);

  // One request for the whole timeline. The list endpoint now returns each
  // run's persisted health score and severity counts, replacing the previous
  // fan-out of one `GET /api/audits/{id}` per run just to read a few numbers.
  const runsQuery = useQuery({
    queryKey: ["audits", repoId],
    queryFn: () => api.listAudits(repoId),
    enabled: !!repoId,
  });

  const runs = useMemo(
    () => (runsQuery.data ?? []).filter((r) => r.status === "done").slice(0, 20).reverse(),
    [runsQuery.data],
  );

  const recurringQuery = useQuery({
    queryKey: ["recurring", repoId],
    queryFn: () => api.recurringFindings(repoId),
    enabled: !!repoId,
  });

  const kbQuery = useQuery({
    queryKey: ["knowledge-base", repoId],
    queryFn: () => api.knowledgeBase(repoId),
    enabled: !!repoId,
  });

  const trendData = runs.map((r) => ({
    date: formatTimestamp(r.ts),
    health: r.health_score?.overall ?? null,
    security: r.health_score?.security ?? null,
    documentation: r.health_score?.documentation ?? null,
  }));

  const severityTrendData = runs.map((r) => ({ date: formatTimestamp(r.ts), ...r.severity_counts }));

  const frequencyData = useMemo(() => {
    const source = recurringQuery.data?.findings ?? [];
    const counts = new Map<string, number>();
    source.forEach((f) => counts.set(f.rule, (counts.get(f.rule) ?? 0) + f.run_count));
    return Array.from(counts.entries())
      .map(([rule, count]) => ({ rule, count }))
      .sort((a, b) => b.count - a.count)
      .slice(0, 8);
  }, [recurringQuery.data]);

  const [runA, setRunA] = useState<string>("");
  const [runB, setRunB] = useState<string>("");
  const [comparePair, setComparePair] = useState<{ a: string; b: string } | null>(null);
  const compareQuery = useQuery({
    queryKey: ["compare", comparePair?.a, comparePair?.b],
    queryFn: () => api.compareRuns(comparePair!.a, comparePair!.b),
    enabled: !!comparePair,
  });

  // Reset the run pickers when the selected repository changes — comparing
  // a run of one repo against a run of another produces a diff where every
  // finding looks "new" and "fixed" simultaneously.
  useEffect(() => {
    setRunA("");
    setRunB("");
    setComparePair(null);
  }, [repoId]);

  const [kbQueryText, setKbQueryText] = useState("");
  const [kbSubmitted, setKbSubmitted] = useState("");
  const kbSearchQuery = useQuery({
    queryKey: ["kb-search", repoId, kbSubmitted],
    queryFn: () => api.searchKnowledgeBase(repoId, kbSubmitted),
    enabled: !!repoId && !!kbSubmitted,
  });

  if (reposQuery.isLoading) {
    return (
      <>
        <TopBar title="Memory" subtitle="Persistent audit history, trends, and knowledge base" />
        <div className="space-y-4 p-8">
          <Skeleton className="h-64 w-full" />
        </div>
      </>
    );
  }

  if (!repositories.length) {
    return (
      <>
        <TopBar title="Memory" subtitle="Persistent audit history, trends, and knowledge base" />
        <div className="p-8">
          <EmptyState
            icon={<Database size={28} />}
            title="No history yet"
            description="Run a few audits to build up trend data here."
          />
        </div>
      </>
    );
  }

  const activeRepo = repositories.find((r) => r.repo_id === repoId);

  return (
    <>
      <TopBar
        title="Memory"
        subtitle="Persistent audit history, trends, and knowledge base"
        right={
          <select
            value={repoId}
            onChange={(e) => setRepoId(e.target.value)}
            className="rounded-lg border border-hairline bg-panel px-3 py-2 text-sm text-fog-1"
          >
            {repositories.map((r) => (
              <option key={r.repo_id} value={r.repo_id}>
                {shortRepoName(r.repo_source)} ({r.run_count} run{r.run_count === 1 ? "" : "s"})
              </option>
            ))}
          </select>
        }
      />
      <div className="space-y-6 p-8">
        {activeRepo && (
          <p className="text-xs text-fog-2">
            Showing {runs.length} run{runs.length === 1 ? "" : "s"} for{" "}
            <span className="text-fog-1">{activeRepo.repo_source}</span>
          </p>
        )}

        {runs.length < 2 && (
          <Card>
            <CardBody className="py-4 text-sm text-fog-2">
              Only {runs.length} completed run recorded for this repository — trends appear once there
              are at least two.
            </CardBody>
          </Card>
        )}

        <div className="grid grid-cols-1 gap-6 lg:grid-cols-2">
          <Card>
            <CardHeader>
              <CardTitle>Health Score Trend</CardTitle>
            </CardHeader>
            <CardBody>
              {runsQuery.isLoading ? (
                <Skeleton className="h-64 w-full" />
              ) : (
                <ResponsiveContainer width="100%" height={240}>
                  <LineChart data={trendData}>
                    <CartesianGrid stroke="var(--color-hairline)" strokeDasharray="3 3" />
                    <XAxis dataKey="date" stroke="var(--color-fog-2)" fontSize={11} />
                    <YAxis stroke="var(--color-fog-2)" fontSize={11} domain={[0, 100]} />
                    <Tooltip contentStyle={chartTooltipStyle} />
                    <Legend wrapperStyle={{ fontSize: 11 }} />
                    <Line type="monotone" dataKey="health" stroke="var(--color-signal)" strokeWidth={2} dot={{ r: 3 }} name="Overall" connectNulls />
                    <Line type="monotone" dataKey="security" stroke="var(--color-critical)" strokeWidth={1.5} dot={{ r: 2 }} name="Security" connectNulls />
                    <Line type="monotone" dataKey="documentation" stroke="var(--color-info)" strokeWidth={1.5} dot={{ r: 2 }} name="Docs" connectNulls />
                  </LineChart>
                </ResponsiveContainer>
              )}
            </CardBody>
          </Card>

          <Card>
            <CardHeader>
              <CardTitle>Severity Trend</CardTitle>
            </CardHeader>
            <CardBody>
              {runsQuery.isLoading ? (
                <Skeleton className="h-64 w-full" />
              ) : (
                <ResponsiveContainer width="100%" height={240}>
                  <LineChart data={severityTrendData}>
                    <CartesianGrid stroke="var(--color-hairline)" strokeDasharray="3 3" />
                    <XAxis dataKey="date" stroke="var(--color-fog-2)" fontSize={11} />
                    <YAxis stroke="var(--color-fog-2)" fontSize={11} allowDecimals={false} />
                    <Tooltip contentStyle={chartTooltipStyle} />
                    <Legend wrapperStyle={{ fontSize: 11 }} />
                    {(["high", "medium", "low", "info"] as const).map((sev) => (
                      <Line key={sev} type="monotone" dataKey={sev} stroke={SEVERITY_LINE_COLOR[sev]} strokeWidth={2} dot={{ r: 2 }} name={sev} />
                    ))}
                  </LineChart>
                </ResponsiveContainer>
              )}
            </CardBody>
          </Card>

          <Card>
            <CardHeader>
              <CardTitle>Issue Frequency</CardTitle>
              <span className="text-xs text-fog-2">across all runs of this repo</span>
            </CardHeader>
            <CardBody>
              {recurringQuery.isLoading ? (
                <Skeleton className="h-64 w-full" />
              ) : frequencyData.length === 0 ? (
                <p className="py-8 text-center text-sm text-fog-2">
                  No issue has appeared in more than one run yet.
                </p>
              ) : (
                <ResponsiveContainer width="100%" height={240}>
                  <BarChart data={frequencyData} layout="vertical" margin={{ left: 8 }}>
                    <CartesianGrid stroke="var(--color-hairline)" strokeDasharray="3 3" horizontal={false} />
                    <XAxis type="number" stroke="var(--color-fog-2)" fontSize={11} allowDecimals={false} />
                    <YAxis type="category" dataKey="rule" stroke="var(--color-fog-2)" fontSize={10} width={140} />
                    <Tooltip contentStyle={chartTooltipStyle} />
                    <Bar dataKey="count" fill="var(--color-signal)" radius={[0, 4, 4, 0]} name="Occurrences" />
                  </BarChart>
                </ResponsiveContainer>
              )}
            </CardBody>
          </Card>

          {/* Knowledge base — specified for this page but previously had no
              backend endpoint at all, so chunk/embedding counts were never
              shown anywhere. */}
          <Card>
            <CardHeader>
              <CardTitle>Knowledge Base</CardTitle>
              <Database size={15} className="text-fog-2" />
            </CardHeader>
            <CardBody className="space-y-4">
              {kbQuery.isLoading ? (
                <Skeleton className="h-24 w-full" />
              ) : (
                <>
                  <div className="grid grid-cols-2 gap-3">
                    <div className="rounded-lg border border-hairline bg-panel-raised px-3 py-2">
                      <p className="font-mono-nums text-lg text-fog-0">{kbQuery.data?.total_chunks ?? 0}</p>
                      <p className="text-xs text-fog-2">Chunks indexed</p>
                    </div>
                    <div className="rounded-lg border border-hairline bg-panel-raised px-3 py-2">
                      <p className="font-mono-nums text-lg text-fog-0">{kbQuery.data?.embedding_dim ?? 0}</p>
                      <p className="text-xs text-fog-2">Embedding dimensions</p>
                    </div>
                  </div>
                  {!!kbQuery.data?.top_files.length && (
                    <div className="space-y-1">
                      <p className="text-xs font-medium uppercase tracking-wider text-fog-2">
                        Most-indexed files
                      </p>
                      <div className="max-h-40 space-y-1 overflow-y-auto pr-1">
                        {kbQuery.data.top_files.map((f) => (
                          <div key={f.file} className="flex items-center justify-between text-xs">
                            <span className="truncate font-mono-nums text-fog-1">{f.file}</span>
                            <span className="ml-2 shrink-0 font-mono-nums text-fog-2">{f.chunks}</span>
                          </div>
                        ))}
                      </div>
                    </div>
                  )}
                </>
              )}

              <div className="space-y-2 border-t border-hairline pt-3">
                <p className="text-xs font-medium uppercase tracking-wider text-fog-2">Query the index</p>
                <div className="flex gap-2">
                  <div className="relative flex-1">
                    <Search size={14} className="absolute left-2.5 top-1/2 -translate-y-1/2 text-fog-2" />
                    <input
                      value={kbQueryText}
                      onChange={(e) => setKbQueryText(e.target.value)}
                      onKeyDown={(e) => e.key === "Enter" && setKbSubmitted(kbQueryText.trim())}
                      placeholder="e.g. password hashing"
                      className="w-full rounded-lg border border-hairline bg-panel py-1.5 pl-8 pr-2 text-xs text-fog-0 placeholder:text-fog-2 focus:border-signal"
                    />
                  </div>
                  <Button size="sm" variant="secondary" onClick={() => setKbSubmitted(kbQueryText.trim())} disabled={!kbQueryText.trim()}>
                    Search
                  </Button>
                </div>
                {kbSearchQuery.isLoading && <Skeleton className="h-16 w-full" />}
                {kbSearchQuery.data && (
                  <div className="max-h-48 space-y-2 overflow-y-auto pr-1">
                    {kbSearchQuery.data.results.length === 0 && (
                      <p className="text-xs text-fog-2">No matching chunks.</p>
                    )}
                    {kbSearchQuery.data.results.map((r) => (
                      <div key={`${r.file}:${r.start_line}`} className="rounded-lg border border-hairline-soft bg-ink p-2">
                        <p className="font-mono-nums text-[11px] text-fog-2">
                          {r.file}:{r.start_line} · score {r.score.toFixed(3)}
                        </p>
                        <pre className="mt-1 max-h-20 overflow-hidden whitespace-pre-wrap font-mono-nums text-[11px] text-fog-1">
                          {r.text.slice(0, 300)}
                        </pre>
                      </div>
                    ))}
                  </div>
                )}
              </div>
            </CardBody>
          </Card>
        </div>

        {/* Recurring findings — required by the spec, previously absent. */}
        <Card>
          <CardHeader>
            <CardTitle>Recurring Findings</CardTitle>
            <Repeat size={15} className="text-fog-2" />
          </CardHeader>
          <CardBody>
            {recurringQuery.isLoading ? (
              <Skeleton className="h-24 w-full" />
            ) : !recurringQuery.data?.findings.length ? (
              <p className="py-6 text-center text-sm text-fog-2">
                Nothing has recurred across runs of this repository yet.
              </p>
            ) : (
              <div className="max-h-80 space-y-1.5 overflow-y-auto pr-1">
                {recurringQuery.data.findings.slice(0, 50).map((f) => (
                  <div
                    key={f.fingerprint}
                    className="flex items-center justify-between gap-3 rounded-lg border border-hairline bg-panel px-3 py-2 text-sm"
                  >
                    <div className="flex min-w-0 items-center gap-2.5">
                      <SeverityBadge severity={f.severity} />
                      <span className="truncate text-fog-0">{f.title}</span>
                      <span className="shrink-0 font-mono-nums text-xs text-fog-2">
                        {f.file}:{f.line}
                      </span>
                    </div>
                    <Badge variant="warning">{f.run_count} runs</Badge>
                  </div>
                ))}
              </div>
            )}
          </CardBody>
        </Card>

        <Card>
          <CardHeader>
            <CardTitle>Repository Timeline</CardTitle>
          </CardHeader>
          <CardBody className="space-y-2">
            {runs
              .slice()
              .reverse()
              .map((r) => (
                <div
                  key={r.run_id}
                  className="flex items-center justify-between rounded-lg border border-hairline bg-panel px-4 py-2.5 text-sm"
                >
                  <div className="flex items-center gap-3">
                    <span className="font-mono-nums text-xs text-fog-2">{formatTimestamp(r.ts)}</span>
                    <span className="text-fog-0">{shortRepoName(r.repo_source)}</span>
                  </div>
                  <div className="flex items-center gap-3">
                    {r.health_score ? (
                      <Badge variant="signal">{r.health_score.overall} health</Badge>
                    ) : (
                      <span className="text-xs text-fog-2">no score recorded</span>
                    )}
                    <span className="font-mono-nums text-xs text-critical">{r.severity_counts.high}H</span>
                    <span className="font-mono-nums text-xs text-warning">{r.severity_counts.medium}M</span>
                    <span className="font-mono-nums text-xs text-caution">{r.severity_counts.low}L</span>
                    <span className="font-mono-nums text-xs text-fog-2">{r.chunks_indexed ?? 0} chunks</span>
                  </div>
                </div>
              ))}
          </CardBody>
        </Card>

        <Card>
          <CardHeader>
            <CardTitle>Audit Run Comparison</CardTitle>
            <GitCompare size={15} className="text-fog-2" />
          </CardHeader>
          <CardBody className="space-y-4">
            <div className="flex flex-wrap items-center gap-3">
              <select
                value={runA}
                onChange={(e) => setRunA(e.target.value)}
                className="rounded-lg border border-hairline bg-panel px-3 py-2 text-sm text-fog-1"
              >
                <option value="">Baseline run…</option>
                {runs.map((r) => (
                  <option key={r.run_id} value={r.run_id}>
                    {formatTimestamp(r.ts)} — {r.run_id}
                  </option>
                ))}
              </select>
              <span className="text-fog-2">vs</span>
              <select
                value={runB}
                onChange={(e) => setRunB(e.target.value)}
                className="rounded-lg border border-hairline bg-panel px-3 py-2 text-sm text-fog-1"
              >
                <option value="">Compare run…</option>
                {runs.map((r) => (
                  <option key={r.run_id} value={r.run_id}>
                    {formatTimestamp(r.ts)} — {r.run_id}
                  </option>
                ))}
              </select>
              {/* The button previously rendered but did nothing — the query ran
                  itself off the select values. It now actually triggers the run. */}
              <Button
                size="sm"
                variant="secondary"
                disabled={!runA || !runB || runA === runB}
                onClick={() => setComparePair({ a: runA, b: runB })}
              >
                <GitCompare size={13} /> Compare
              </Button>
              {runA && runB && runA === runB && (
                <span className="text-xs text-warning">Pick two different runs.</span>
              )}
            </div>

            {compareQuery.isLoading && <Skeleton className="h-24 w-full" />}
            {compareQuery.isError && (
              <p className="text-sm text-critical">Comparison failed. Try re-selecting the runs.</p>
            )}
            {compareQuery.data && (
              <div className="space-y-3">
                <p className="text-sm text-fog-1">{compareQuery.data.trend_summary}</p>
                <div className="grid grid-cols-2 gap-3 sm:grid-cols-4">
                  <div className="rounded-lg border border-hairline bg-panel-raised px-3 py-2 text-center">
                    <p className="font-mono-nums text-lg text-critical">{compareQuery.data.new_findings.length}</p>
                    <p className="text-xs text-fog-2">New</p>
                  </div>
                  <div className="rounded-lg border border-hairline bg-panel-raised px-3 py-2 text-center">
                    <p className="font-mono-nums text-lg text-success">{compareQuery.data.fixed_findings.length}</p>
                    <p className="text-xs text-fog-2">Fixed</p>
                  </div>
                  <div className="rounded-lg border border-hairline bg-panel-raised px-3 py-2 text-center">
                    <p className="font-mono-nums text-lg text-warning">{compareQuery.data.recurring_findings.length}</p>
                    <p className="text-xs text-fog-2">Recurring</p>
                  </div>
                  <div className="rounded-lg border border-hairline bg-panel-raised px-3 py-2 text-center">
                    <p
                      className={`font-mono-nums text-lg ${
                        compareQuery.data.health_score_delta >= 0 ? "text-success" : "text-critical"
                      }`}
                    >
                      {compareQuery.data.health_score_delta > 0 ? "+" : ""}
                      {compareQuery.data.health_score_delta}
                    </p>
                    <p className="text-xs text-fog-2">Health Δ</p>
                  </div>
                </div>
                {!!compareQuery.data.severity_changes.length && (
                  <div className="space-y-1">
                    <p className="text-xs font-medium uppercase tracking-wider text-fog-2">Severity changes</p>
                    {compareQuery.data.severity_changes.slice(0, 10).map((c, i) => (
                      <p key={i} className="font-mono-nums text-xs text-fog-1">
                        {String(c.file)}:{String(c.line)} — {String(c.from_severity)} → {String(c.to_severity)}
                      </p>
                    ))}
                  </div>
                )}
              </div>
            )}
          </CardBody>
        </Card>
      </div>
    </>
  );
}
