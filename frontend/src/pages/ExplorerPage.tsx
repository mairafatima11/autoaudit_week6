import { useEffect, useMemo, useState } from "react";
import { useQuery, useMutation } from "@tanstack/react-query";
import { useSearchParams } from "react-router-dom";
import { FolderTree, Sparkles, Wrench, Loader2 } from "lucide-react";
import { TopBar } from "../components/TopBar";
import { Card, CardBody, CardHeader, CardTitle } from "../components/ui/Card";
import { Button, EmptyState, Skeleton } from "../components/ui/primitives";
import { FileTree } from "../components/FileTree";
import { CodeViewer } from "../components/CodeViewer";
import { SeverityBadge } from "../components/FindingCard";
import { api } from "../lib/api";
import { useRunContext } from "../lib/RunContext";
import type { FileFindingRef } from "../lib/types";

export function ExplorerPage() {
  const { activeRunId } = useRunContext();
  const [searchParams, setSearchParams] = useSearchParams();
  const [selectedPath, setSelectedPath] = useState<string | null>(searchParams.get("file"));
  const [highlightLine, setHighlightLine] = useState<number | null>(
    searchParams.get("line") ? Number(searchParams.get("line")) : null
  );
  const [selectedFinding, setSelectedFinding] = useState<FileFindingRef | null>(null);

  const treeQuery = useQuery({
    queryKey: ["file-tree", activeRunId],
    queryFn: () => api.getFileTree(activeRunId!),
    enabled: !!activeRunId,
  });

  const auditQuery = useQuery({
    queryKey: ["audit", activeRunId],
    queryFn: () => api.getAudit(activeRunId!),
    enabled: !!activeRunId,
  });

  const findingFiles = useMemo(
    () => new Set((auditQuery.data?.report.findings ?? []).map((f) => f.file)),
    [auditQuery.data]
  );

  const contentQuery = useQuery({
    queryKey: ["file-content", activeRunId, selectedPath],
    queryFn: () => api.getFileContent(activeRunId!, selectedPath!),
    enabled: !!activeRunId && !!selectedPath,
  });

  const fixMutation = useMutation({
    mutationFn: (fingerprint: string) => api.proposeFixes(activeRunId!, { fingerprints: [fingerprint], max_findings: 1 }),
  });

  useEffect(() => {
    // Deep-link support: /explorer?file=...&line=... (used by the "View in Explorer" link on Findings)
    const file = searchParams.get("file");
    const line = searchParams.get("line");
    if (file) setSelectedPath(file);
    if (line) setHighlightLine(Number(line));
  }, [searchParams]);

  function selectFile(path: string) {
    setSelectedPath(path);
    setHighlightLine(null);
    setSelectedFinding(null);
    fixMutation.reset();
    setSearchParams({ file: path });
  }

  function jumpToFinding(f: FileFindingRef) {
    setHighlightLine(f.line);
    setSelectedFinding(f);
    fixMutation.reset();
  }

  if (!activeRunId) {
    return (
      <>
        <TopBar title="Explorer" />
        <div className="p-8">
          <EmptyState icon={<FolderTree size={28} />} title="No repository indexed" description="Run an audit first, then browse its files here." />
        </div>
      </>
    );
  }

  return (
    <>
      <TopBar title="Explorer" subtitle="Browse the repository, jump to findings, view evidence and suggested fixes inline" />
      <div className="grid h-[calc(100vh-88px)] grid-cols-1 gap-4 p-6 lg:grid-cols-12">
        <Card className="overflow-hidden lg:col-span-3">
          <CardHeader>
            <CardTitle>Files</CardTitle>
            {treeQuery.data && <span className="font-mono-nums text-xs text-fog-2">{treeQuery.data.file_count}</span>}
          </CardHeader>
          <CardBody className="max-h-[calc(100vh-160px)] overflow-y-auto pt-0">
            {treeQuery.isLoading && <Skeleton className="h-40 w-full" />}
            {treeQuery.data && (
              <FileTree root={treeQuery.data.tree} selectedPath={selectedPath} onSelect={selectFile} findingFiles={findingFiles} />
            )}
          </CardBody>
        </Card>

        <Card className="overflow-hidden lg:col-span-6">
          <CardHeader>
            <CardTitle className="font-mono-nums normal-case tracking-normal">{selectedPath ?? "Select a file"}</CardTitle>
            {contentQuery.data && <span className="text-xs text-fog-2">{contentQuery.data.findings.length} finding(s)</span>}
          </CardHeader>
          <CardBody>
            {!selectedPath && (
              <EmptyState icon={<FolderTree size={24} />} title="No file selected" description="Choose a file from the tree to view it here." />
            )}
            {selectedPath && contentQuery.isLoading && <Skeleton className="h-96 w-full" />}
            {contentQuery.data && (
              <CodeViewer
                content={contentQuery.data.content}
                language={contentQuery.data.language}
                findings={contentQuery.data.findings}
                highlightLine={highlightLine}
                onLineClick={(line) => {
                  const match = contentQuery.data!.findings.find((f) => f.line === line);
                  if (match) jumpToFinding(match);
                }}
              />
            )}
          </CardBody>
        </Card>

        <Card className="overflow-hidden lg:col-span-3">
          <CardHeader>
            <CardTitle>Findings in file</CardTitle>
          </CardHeader>
          <CardBody className="max-h-[calc(100vh-160px)] space-y-4 overflow-y-auto pt-0">
            <div className="space-y-1.5">
              {contentQuery.data?.findings.length === 0 && <p className="text-sm text-fog-2">No findings in this file.</p>}
              {contentQuery.data?.findings.map((f) => (
                <button
                  key={f.fingerprint}
                  onClick={() => jumpToFinding(f)}
                  className={`w-full rounded-lg border px-3 py-2 text-left text-xs transition-colors ${
                    selectedFinding?.fingerprint === f.fingerprint
                      ? "border-signal bg-signal/10"
                      : "border-hairline bg-panel hover:border-fog-2"
                  }`}
                >
                  <div className="mb-1 flex items-center justify-between">
                    <SeverityBadge severity={f.severity} />
                    <span className="font-mono-nums text-fog-2">:{f.line}</span>
                  </div>
                  <p className="text-fog-0">{f.title}</p>
                  <p className="mt-1 font-mono-nums text-[11px] text-fog-2">{Math.round(f.confidence * 100)}% confidence</p>
                </button>
              ))}
            </div>

            {selectedFinding && (
              <div className="space-y-3 border-t border-hairline pt-4">
                <p className="text-xs font-medium uppercase tracking-wider text-fog-2">AI Explanation</p>
                <p className="text-sm text-fog-1">{selectedFinding.title}</p>
                <p className="font-mono-nums text-xs text-fog-2">
                  rule: {selectedFinding.rule} · via {selectedFinding.source_agent} ·{" "}
                  {Math.round(selectedFinding.confidence * 100)}% confidence
                </p>

                <Button size="sm" onClick={() => fixMutation.mutate(selectedFinding.fingerprint)} disabled={fixMutation.isPending}>
                  {fixMutation.isPending ? <Loader2 size={12} className="animate-spin" /> : <Wrench size={12} />}
                  Suggest Fix
                </Button>

                {fixMutation.data?.[0] && (
                  <div className="space-y-2 rounded-lg border border-hairline bg-panel-raised p-3">
                    <div className="flex items-center gap-1.5 text-xs text-signal-glow">
                      <Sparkles size={12} /> {fixMutation.data[0].pr_title}
                    </div>
                    <pre className="max-h-40 overflow-auto whitespace-pre-wrap font-mono-nums text-[11px] text-fog-1">
                      {fixMutation.data[0].patch}
                    </pre>
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
