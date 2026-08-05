import { useQuery } from "@tanstack/react-query";
import { useEffect, useRef } from "react";
import { CheckCircle2, ScanSearch, XCircle } from "lucide-react";
import { TopBar } from "../components/TopBar";
import { Card, CardBody, CardHeader, CardTitle } from "../components/ui/Card";
import { EmptyState, Skeleton } from "../components/ui/primitives";
import { PipelineRail } from "../components/PipelineRail";
import { api } from "../lib/api";
import { useRunContext } from "../lib/RunContext";

export function AuditPage() {
  const { activeRunId } = useRunContext();
  const logRef = useRef<HTMLDivElement>(null);

  const statusQuery = useQuery({
    queryKey: ["status", activeRunId],
    queryFn: () => api.getAuditStatus(activeRunId!),
    enabled: !!activeRunId,
    refetchInterval: (query) => (query.state.data?.status === "running" ? 1200 : 4000),
  });

  const eventsQuery = useQuery({
    queryKey: ["events", activeRunId],
    queryFn: () => api.getAuditEvents(activeRunId!),
    enabled: !!activeRunId,
    refetchInterval: () => (statusQuery.data?.status === "running" ? 1200 : false),
  });

  useEffect(() => {
    logRef.current?.scrollTo({ top: logRef.current.scrollHeight, behavior: "smooth" });
  }, [eventsQuery.data]);

  if (!activeRunId) {
    return (
      <>
        <TopBar title="Audit" subtitle="Live execution of the multi-agent pipeline" />
        <div className="p-8">
          <EmptyState
            icon={<ScanSearch size={28} />}
            title="No audit running"
            description="Start an audit from the Dashboard to watch the agent pipeline execute live here."
          />
        </div>
      </>
    );
  }

  const status = statusQuery.data;

  return (
    <>
      <TopBar
        title="Audit"
        subtitle={`Run ${activeRunId}`}
        right={
          status && (
            <span
              className={
                status.status === "running"
                  ? "flex items-center gap-1.5 text-sm text-signal-glow"
                  : status.status === "error"
                    ? "flex items-center gap-1.5 text-sm text-critical"
                    : "flex items-center gap-1.5 text-sm text-success"
              }
            >
              {status.status === "error" ? <XCircle size={15} /> : <CheckCircle2 size={15} />}
              {status.status}
            </span>
          )
        }
      />
      <div className="space-y-6 p-8">
        <Card>
          <CardHeader>
            <CardTitle>Live Agent Execution</CardTitle>
            {status && <span className="font-mono-nums text-xs text-fog-2">{status.percent}%</span>}
          </CardHeader>
          <CardBody>
            {status ? <PipelineRail stages={status.stages} size="lg" /> : <Skeleton className="h-20 w-full" />}
            <div className="mt-4 h-1.5 w-full overflow-hidden rounded-full bg-panel-raised">
              <div
                className="h-full rounded-full bg-signal transition-all duration-500"
                style={{ width: `${status?.percent ?? 0}%` }}
              />
            </div>
            {status?.error && (
              <p className="mt-3 rounded-lg border border-critical/30 bg-critical-dim px-3 py-2 text-sm text-critical">
                {status.error}
              </p>
            )}
          </CardBody>
        </Card>

        <Card>
          <CardHeader>
            <CardTitle>Streaming Logs</CardTitle>
          </CardHeader>
          <CardBody>
            <div ref={logRef} className="max-h-96 space-y-1 overflow-y-auto rounded-lg border border-hairline-soft bg-ink p-4 font-mono-nums text-xs">
              {eventsQuery.data?.events.length ? (
                eventsQuery.data.events.map((ev, i) => (
                  <div key={i} className="flex gap-3">
                    <span className="shrink-0 text-fog-2">{new Date(ev.ts * 1000).toLocaleTimeString()}</span>
                    <span className="shrink-0 text-signal-glow">{String(ev.actor)}</span>
                    <span className="text-fog-1">{String(ev.event)}</span>
                  </div>
                ))
              ) : (
                <p className="text-fog-2">Waiting for events…</p>
              )}
            </div>
          </CardBody>
        </Card>
      </div>
    </>
  );
}
