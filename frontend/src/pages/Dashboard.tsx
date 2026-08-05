import { useQuery } from "@tanstack/react-query";
import { useNavigate } from "react-router-dom";
import { AlertTriangle, Database, FileWarning, GitBranch, ShieldAlert, Sparkles, Cpu } from "lucide-react";
import { TopBar } from "../components/TopBar";
import { Card, CardBody, CardHeader, CardTitle } from "../components/ui/Card";
import { Button, EmptyState, Skeleton } from "../components/ui/primitives";
import { StatCard } from "../components/StatCard";
import { HealthGauge, CategoryBar } from "../components/HealthGauge";
import { PipelineRail } from "../components/PipelineRail";
import { api } from "../lib/api";
import { useRunContext } from "../lib/RunContext";
import { formatRelativeTime, shortRepoName } from "../lib/utils";

export function Dashboard() {
  const navigate = useNavigate();
  const { activeRunId, setActiveRunId, lastSource, setLastSource } = useRunContext();

  // Wrapped rather than passed by reference: `listAudits` takes an optional
  // repo filter, and React Query would otherwise hand it its query context
  // object as that argument.
  const runsQuery = useQuery({ queryKey: ["audits"], queryFn: () => api.listAudits(), refetchInterval: 5000 });
  const auditQuery = useQuery({
    queryKey: ["audit", activeRunId],
    queryFn: () => api.getAudit(activeRunId!),
    enabled: !!activeRunId,
  });
  const statusQuery = useQuery({
    queryKey: ["status", activeRunId],
    queryFn: () => api.getAuditStatus(activeRunId!),
    enabled: !!activeRunId,
    refetchInterval: (query) => (query.state.data?.status === "running" ? 1500 : false),
  });

  async function runAudit() {
    const { run_id } = await api.startAudit(lastSource);
    setActiveRunId(run_id);
    navigate("/audit");
  }

  const kbQuery = useQuery({
    queryKey: ["knowledge-base", auditQuery.data?.report.repo_id],
    queryFn: () => api.knowledgeBase(auditQuery.data!.report.repo_id),
    enabled: !!auditQuery.data?.report.repo_id,
  });
  const modelsQuery = useQuery({ queryKey: ["models"], queryFn: api.availableModels });

  const report = auditQuery.data?.report;
  const health = auditQuery.data?.health_score;

  // `report.findings` also carries `fixed` entries — issues the audit-history
  // diff reconstructed because they were resolved since the last run. Counting
  // them here made the severity tiles report problems that no longer exist
  // (and the count could *rise* after a fix). Only open findings are current.
  const openFindings = report?.findings.filter((f) => f.status !== "fixed") ?? [];
  const fixedCount = (report?.findings.length ?? 0) - openFindings.length;
  const severityCounts = { high: 0, medium: 0, low: 0, info: 0 };
  openFindings.forEach((f) => {
    if (f.severity in severityCounts) severityCounts[f.severity] += 1;
  });

  return (
    <>
      <TopBar
        title="Dashboard"
        subtitle={report ? shortRepoName(report.repo_source) : "No audit selected yet"}
        right={
          <>
            <input
              value={lastSource}
              onChange={(e) => setLastSource(e.target.value)}
              placeholder="repo path or git URL"
              className="w-64 rounded-lg border border-hairline bg-panel px-3 py-2 text-sm text-fog-0 placeholder:text-fog-2 focus:border-signal"
            />
            <Button onClick={runAudit}>
              <Sparkles size={14} /> Run Audit
            </Button>
          </>
        }
      />

      <div className="space-y-6 p-8">
        {!activeRunId && !runsQuery.data?.length && (
          <EmptyState
            icon={<GitBranch size={28} />}
            title="No audits yet"
            description="Point AutoAudit AI at a repository and run your first audit to see health scores, findings, and trends here."
            action={
              <Button onClick={runAudit}>
                <Sparkles size={14} /> Run first audit
              </Button>
            }
          />
        )}

        {/* A run can now complete with some model-authored text missing
            (provider outage). Detection is deterministic and unaffected, but
            the user must not mistake a placeholder for a real explanation. */}
        {!!report?.degraded_suggestions && (
          <div className="flex items-start gap-3 rounded-xl border border-warning/40 bg-warning-dim px-4 py-3">
            <AlertTriangle size={16} className="mt-0.5 shrink-0 text-warning" />
            <div className="text-sm">
              <p className="font-medium text-fog-0">Some descriptions could not be generated</p>
              <p className="mt-0.5 text-fog-1">
                {report.degraded_suggestions} item
                {report.degraded_suggestions === 1 ? "" : "s"} kept a heuristic description because
                every model provider was unavailable. Detection, severities and evidence are
                unaffected — re-run the audit to fill in the missing text.
              </p>
            </div>
          </div>
        )}

        {activeRunId && (
          <div className="grid grid-cols-1 gap-6 lg:grid-cols-3">
            <Card className="lg:col-span-1">
              <CardHeader>
                <CardTitle>Repository Health Score</CardTitle>
              </CardHeader>
              <CardBody className="flex flex-col items-center gap-5">
                {auditQuery.isLoading ? (
                  <Skeleton className="h-32 w-32 rounded-full" />
                ) : health ? (
                  <HealthGauge score={health.overall} />
                ) : null}
                {health && (
                  <div className="w-full space-y-3">
                    <CategoryBar label="Security" score={health.security} />
                    <CategoryBar label="Quality" score={health.quality} />
                    <CategoryBar label="Documentation" score={health.documentation} />
                    <CategoryBar label="Architecture" score={health.architecture} />
                    {/* Test coverage is part of the score, so it belongs in the
                        breakdown — it was previously computed and then not
                        rendered, leaving the bars unable to explain the total. */}
                    {health.test_coverage_measured ? (
                      <CategoryBar
                        label="Test coverage"
                        score={health.test_coverage}
                        hint={
                          report?.test_coverage
                            ? `${report.test_coverage.modules_with_tests}/${report.test_coverage.source_files} modules covered · ${report.test_coverage.test_cases} test cases`
                            : "heuristic signal"
                        }
                      />
                    ) : (
                      <div className="flex items-center justify-between text-xs">
                        <span className="text-fog-1">Test coverage</span>
                        <span className="text-fog-2">not measured</span>
                      </div>
                    )}
                    <CategoryBar label="Technical debt" score={health.technical_debt} />
                  </div>
                )}
              </CardBody>
            </Card>

            <Card className="lg:col-span-2">
              <CardHeader>
                <CardTitle>Pipeline Status</CardTitle>
              </CardHeader>
              <CardBody>
                {statusQuery.data ? (
                  <PipelineRail stages={statusQuery.data.stages} size="sm" />
                ) : (
                  <Skeleton className="h-16 w-full" />
                )}
                <div className="mt-5 grid grid-cols-2 gap-3 sm:grid-cols-4">
                  <StatCard label="High" value={severityCounts.high} icon={ShieldAlert} tone="critical" />
                  <StatCard label="Medium" value={severityCounts.medium} icon={AlertTriangle} tone="warning" />
                  <StatCard label="Low" value={severityCounts.low} icon={FileWarning} tone="signal" />
                  <StatCard label="Files scanned" value={report?.files_scanned ?? "—"} />
                </div>
                {report && !report.is_first_run && (
                  <p className="mt-3 text-xs text-fog-2">
                    Open findings only.{" "}
                    {fixedCount > 0 ? (
                      <span className="text-success">{fixedCount} fixed since the previous run</span>
                    ) : (
                      "No findings fixed since the previous run"
                    )}
                    .
                  </p>
                )}
              </CardBody>
            </Card>

            {/* Memory + model status: both are listed as Dashboard content in
                the spec and previously had no representation anywhere. */}
            <Card className="lg:col-span-3">
              <CardHeader>
                <CardTitle>System Status</CardTitle>
              </CardHeader>
              <CardBody className="grid grid-cols-1 gap-4 sm:grid-cols-2">
                <div className="rounded-lg border border-hairline bg-panel p-4">
                  <div className="mb-3 flex items-center gap-2 text-sm text-fog-0">
                    <Database size={15} className="text-signal" /> Memory
                  </div>
                  {kbQuery.isLoading ? (
                    <Skeleton className="h-12 w-full" />
                  ) : (
                    <dl className="grid grid-cols-3 gap-3 text-xs">
                      <div>
                        <dt className="text-fog-2">Chunks indexed</dt>
                        <dd className="font-mono-nums text-fog-0">{kbQuery.data?.total_chunks ?? "—"}</dd>
                      </div>
                      <div>
                        <dt className="text-fog-2">Embedding dim</dt>
                        <dd className="font-mono-nums text-fog-0">{kbQuery.data?.embedding_dim ?? "—"}</dd>
                      </div>
                      <div>
                        <dt className="text-fog-2">Past runs</dt>
                        <dd className="font-mono-nums text-fog-0">{runsQuery.data?.length ?? "—"}</dd>
                      </div>
                    </dl>
                  )}
                </div>
                <div className="rounded-lg border border-hairline bg-panel p-4">
                  <div className="mb-3 flex items-center gap-2 text-sm text-fog-0">
                    <Cpu size={15} className="text-signal" /> Models
                  </div>
                  {modelsQuery.isLoading ? (
                    <Skeleton className="h-12 w-full" />
                  ) : (
                    <ul className="space-y-1.5 text-xs">
                      {modelsQuery.data?.providers.map((p) => (
                        <li key={p.id} className="flex items-center justify-between">
                          <span className="text-fog-1">
                            {p.id} <span className="text-fog-2">· {p.model}</span>
                          </span>
                          <span className={p.live ? "text-success" : "text-fog-2"}>
                            {p.live ? "live" : "mock"}
                          </span>
                        </li>
                      ))}
                    </ul>
                  )}
                </div>
              </CardBody>
            </Card>
          </div>
        )}

        <Card>
          <CardHeader>
            <CardTitle>Recent Runs</CardTitle>
          </CardHeader>
          <CardBody className="space-y-2">
            {runsQuery.isLoading && <Skeleton className="h-10 w-full" />}
            {runsQuery.data?.length === 0 && <p className="text-sm text-fog-2">No runs recorded yet.</p>}
            {runsQuery.data?.slice(0, 8).map((run) => (
              <button
                key={run.run_id}
                onClick={() => setActiveRunId(run.run_id)}
                className="flex w-full items-center justify-between rounded-lg border border-hairline bg-panel px-4 py-2.5 text-left text-sm transition-colors hover:border-fog-2"
              >
                <div className="flex items-center gap-3">
                  <span className="font-mono-nums text-xs text-fog-2">{formatRelativeTime(run.ts)}</span>
                  <span className="text-fog-0">{shortRepoName(run.repo_source)}</span>
                </div>
                <span
                  className={
                    run.status === "running"
                      ? "text-signal-glow"
                      : run.status === "error"
                        ? "text-critical"
                        : "text-success"
                  }
                >
                  {run.status}
                </span>
              </button>
            ))}
          </CardBody>
        </Card>
      </div>
    </>
  );
}
