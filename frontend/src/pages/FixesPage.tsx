import { useQuery } from "@tanstack/react-query";
import { Copy, Download, Loader2, Wrench } from "lucide-react";
import { TopBar } from "../components/TopBar";
import { Card, CardBody, CardHeader, CardTitle } from "../components/ui/Card";
import { Badge, Button, EmptyState } from "../components/ui/primitives";
import { PendingWork } from "../components/PendingWork";
import { api, LONG_TIMEOUT_MS } from "../lib/api";
import { useRunContext } from "../lib/RunContext";
import type { FixProposal } from "../lib/types";

function download(filename: string, text: string) {
  const blob = new Blob([text], { type: "text/plain" });
  const url = URL.createObjectURL(blob);
  const a = document.createElement("a");
  a.href = url;
  a.download = filename;
  a.click();
  URL.revokeObjectURL(url);
}

function FixCard({ fix }: { fix: FixProposal }) {
  const impactVariant = fix.estimated_impact === "high" ? "critical" : fix.estimated_impact === "medium" ? "warning" : "neutral";
  return (
    <Card>
      <CardHeader>
        <CardTitle>{fix.pr_title}</CardTitle>
        <div className="flex items-center gap-2">
          <Badge variant={impactVariant}>{fix.estimated_impact} impact</Badge>
          <Badge variant="signal">{Math.round(fix.estimated_confidence * 100)}% confidence</Badge>
        </div>
      </CardHeader>
      <CardBody className="space-y-4">
        <p className="text-sm text-fog-1">{fix.pr_description}</p>

        <div>
          <div className="mb-1.5 flex items-center justify-between">
            <p className="text-xs font-medium uppercase tracking-wider text-fog-2">Patch</p>
            <div className="flex gap-1.5">
              <Button size="sm" variant="ghost" onClick={() => navigator.clipboard.writeText(fix.patch)}>
                <Copy size={12} /> Copy
              </Button>
              <Button size="sm" variant="ghost" onClick={() => download(`${fix.file.replace(/\//g, "_")}.patch`, fix.patch)}>
                <Download size={12} /> Download
              </Button>
            </div>
          </div>
          <pre className="overflow-x-auto rounded-lg border border-hairline-soft bg-ink p-3 font-mono-nums text-xs leading-relaxed">
            {fix.patch.split("\n").map((line, i) => (
              <div
                key={i}
                className={
                  line.startsWith("+") && !line.startsWith("+++")
                    ? "text-success"
                    : line.startsWith("-") && !line.startsWith("---")
                      ? "text-critical"
                      : "text-fog-2"
                }
              >
                {line || " "}
              </div>
            ))}
          </pre>
        </div>

        <div className="grid grid-cols-1 gap-3 sm:grid-cols-2">
          <div>
            <p className="mb-1 text-xs font-medium uppercase tracking-wider text-fog-2">Commit message</p>
            <code className="block rounded-lg border border-hairline-soft bg-panel-raised px-3 py-2 text-xs">{fix.commit_message}</code>
          </div>
          <div>
            <p className="mb-1 text-xs font-medium uppercase tracking-wider text-fog-2">File</p>
            <code className="block rounded-lg border border-hairline-soft bg-panel-raised px-3 py-2 text-xs">{fix.file}</code>
          </div>
        </div>

        <div className="grid grid-cols-1 gap-3 sm:grid-cols-2">
          <div>
            <p className="mb-1 text-xs font-medium uppercase tracking-wider text-fog-2">Suggested unit test</p>
            <p className="rounded-lg border border-hairline-soft bg-panel-raised px-3 py-2 text-xs text-fog-1">
              {fix.suggested_unit_test}
            </p>
          </div>
          <div>
            <p className="mb-1 text-xs font-medium uppercase tracking-wider text-fog-2">Suggested integration test</p>
            <p className="rounded-lg border border-hairline-soft bg-panel-raised px-3 py-2 text-xs text-fog-1">
              {fix.suggested_integration_test}
            </p>
          </div>
        </div>
      </CardBody>
    </Card>
  );
}

export function FixesPage() {
  const { activeRunId } = useRunContext();

  const auditQuery = useQuery({
    queryKey: ["audit", activeRunId],
    queryFn: () => api.getAudit(activeRunId!),
    enabled: !!activeRunId,
  });

  // useQuery (not useMutation) so the result is cached under this run's
  // key and survives navigating away to another page and back — the
  // previous useMutation-based version threw its data away on unmount,
  // forcing "Generate Fixes" to be clicked again every time. `enabled:
  // false` keeps it from firing automatically; `refetch()` triggers it.
  const fixesQuery = useQuery({
    queryKey: ["fixes", activeRunId],
    queryFn: () => api.proposeFixes(activeRunId!, {}),
    enabled: false,
    retry: false,
  });

  if (!activeRunId) {
    return (
      <>
        <TopBar title="Fixes" />
        <div className="p-8">
          <EmptyState icon={<Wrench size={28} />} title="No fixes yet" description="Run an audit first, then generate fix proposals here." />
        </div>
      </>
    );
  }

  const findingsCount = auditQuery.data?.report.findings.length ?? 0;

  return (
    <>
      <TopBar
        title="Fixes"
        subtitle="Proposal only — AutoAudit AI never modifies your repository automatically"
        right={
          <Button onClick={() => fixesQuery.refetch()} disabled={fixesQuery.isFetching || findingsCount === 0}>
            {fixesQuery.isFetching ? <Loader2 size={14} className="animate-spin" /> : <Wrench size={14} />}
            Generate Fixes
          </Button>
        }
      />
      <div className="space-y-5 p-8">
        {fixesQuery.isError && (
          <div className="rounded-lg border border-critical/30 bg-critical-dim px-4 py-3 text-sm text-critical">
            Couldn't generate fixes: {(fixesQuery.error as Error).message}
          </div>
        )}
        {!fixesQuery.data && !fixesQuery.isFetching && (
          <EmptyState
            icon={<Wrench size={28} />}
            title="No fix proposals generated yet"
            description={`${findingsCount} finding(s) available. Click "Generate Fixes" to have the Fix Agent draft patches, PR descriptions, and suggested tests.`}
          />
        )}
        {fixesQuery.isFetching && (
          <PendingWork
            label="Fix Agent is drafting proposals…"
            expectedSeconds={30}
            timeoutSeconds={LONG_TIMEOUT_MS / 1000}
          />
        )}
        {fixesQuery.data?.map((fix) => (
          <FixCard key={fix.finding_fingerprint} fix={fix} />
        ))}
      </div>
    </>
  );
}
