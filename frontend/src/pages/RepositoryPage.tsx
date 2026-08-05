import { useQuery } from "@tanstack/react-query";
import { useEffect, useState } from "react";
import { FolderGit2, Sparkles, Star, GitFork, CircleAlert, GitCommitHorizontal } from "lucide-react";
import { useNavigate } from "react-router-dom";
import { TopBar } from "../components/TopBar";
import { Card, CardBody, CardHeader, CardTitle } from "../components/ui/Card";
import { Badge, Button, EmptyState, Skeleton } from "../components/ui/primitives";
import { api } from "../lib/api";
import { useRunContext } from "../lib/RunContext";
import { shortRepoName, formatTimestamp } from "../lib/utils";

function useDebouncedValue<T>(value: T, delayMs: number): T {
  const [debounced, setDebounced] = useState(value);
  useEffect(() => {
    const timer = setTimeout(() => setDebounced(value), delayMs);
    return () => clearTimeout(timer);
  }, [value, delayMs]);
  return debounced;
}

function GitHubMetadataCard({ source }: { source: string }) {
  const debounced = useDebouncedValue(source, 500);
  const looksLikeGitHub = /github\.com/.test(debounced);

  const metaQuery = useQuery({
    queryKey: ["github-metadata", debounced],
    queryFn: () => api.getRepositoryMetadata(debounced),
    enabled: looksLikeGitHub,
    staleTime: 60_000,
  });

  if (!looksLikeGitHub) return null;

  return (
    <Card>
      <CardHeader>
        <CardTitle>GitHub Metadata</CardTitle>
        {metaQuery.data?.available && <Badge variant="success">Live</Badge>}
      </CardHeader>
      <CardBody>
        {metaQuery.isLoading && <Skeleton className="h-24 w-full" />}
        {metaQuery.data && !metaQuery.data.available && (
          <p className="text-sm text-fog-2">
            {metaQuery.data.reason === "not_a_github_url"
              ? "Not recognized as a GitHub URL."
              : `Couldn't fetch GitHub metadata: ${metaQuery.data.reason}`}
          </p>
        )}
        {metaQuery.data?.available && (
          <div className="space-y-3">
            <div className="flex flex-wrap items-center gap-2">
              <span className="font-display text-sm font-semibold text-fog-0">{metaQuery.data.full_name}</span>
              {metaQuery.data.language && <Badge variant="signal">{metaQuery.data.language}</Badge>}
              {metaQuery.data.archived && <Badge variant="warning">Archived</Badge>}
              {metaQuery.data.license && <Badge>{metaQuery.data.license}</Badge>}
            </div>
            {metaQuery.data.description && <p className="text-sm text-fog-1">{metaQuery.data.description}</p>}
            <div className="grid grid-cols-2 gap-3 sm:grid-cols-4">
              <div className="flex items-center gap-1.5 text-sm text-fog-1">
                <Star size={13} className="text-caution" /> <span className="font-mono-nums">{metaQuery.data.stars?.toLocaleString()}</span>
              </div>
              <div className="flex items-center gap-1.5 text-sm text-fog-1">
                <GitFork size={13} className="text-fog-2" /> <span className="font-mono-nums">{metaQuery.data.forks?.toLocaleString()}</span>
              </div>
              <div className="flex items-center gap-1.5 text-sm text-fog-1">
                <CircleAlert size={13} className="text-warning" /> <span className="font-mono-nums">{metaQuery.data.open_issues?.toLocaleString()}</span>
              </div>
              <div className="flex items-center gap-1.5 text-sm text-fog-1">
                <GitCommitHorizontal size={13} className="text-fog-2" /> <span className="font-mono-nums">{metaQuery.data.default_branch}</span>
              </div>
            </div>
            {metaQuery.data.last_commit_author && (
              <div className="rounded-lg border border-hairline bg-panel px-3 py-2 text-xs">
                <p className="text-fog-2">
                  Last commit by <span className="text-fog-0">{metaQuery.data.last_commit_author}</span>
                  {metaQuery.data.last_commit_date && ` · ${formatTimestamp(new Date(metaQuery.data.last_commit_date).getTime() / 1000)}`}
                </p>
                {metaQuery.data.last_commit_message && <p className="mt-1 text-fog-1">{metaQuery.data.last_commit_message}</p>}
              </div>
            )}
            {metaQuery.data.size_kb !== undefined && (
              <p className="text-xs text-fog-2">Repository size: {(metaQuery.data.size_kb / 1024).toFixed(1)} MB</p>
            )}
          </div>
        )}
      </CardBody>
    </Card>
  );
}

export function RepositoryPage() {
  const navigate = useNavigate();
  const { activeRunId, setActiveRunId, lastSource, setLastSource } = useRunContext();
  const [draft, setDraft] = useState(lastSource);
  useEffect(() => {
    setDraft(lastSource);
}, [lastSource]);

  const auditQuery = useQuery({
    queryKey: ["audit", activeRunId],
    queryFn: () => api.getAudit(activeRunId!),
    enabled: !!activeRunId,
  });
  const report = auditQuery.data?.report;

  async function runAudit() {
      const source = draft.trim();
      const { run_id } = await api.startAudit(source);
      setLastSource(source);
      setActiveRunId(run_id);
      navigate("/audit");
  }

  const languages = new Set(report?.findings.map((f) => f.file.split(".").pop()).filter(Boolean));

  return (
    <>
      <TopBar title="Repository" subtitle="Point AutoAudit AI at a repository and inspect it before running a full audit" />
      <div className="space-y-6 p-8">
        <Card>
          <CardBody className="flex flex-col gap-3 pt-5 sm:flex-row sm:items-center">
            <div className="relative flex-1">
              <FolderGit2 size={15} className="absolute left-3 top-1/2 -translate-y-1/2 text-fog-2" />
              <input
                value={draft}
                onChange={(e) => setDraft(e.target.value)}
                placeholder="Local path or git URL (e.g. https://github.com/org/repo.git)"
                className="w-full rounded-lg border border-hairline bg-panel py-2.5 pl-9 pr-3 text-sm text-fog-0 placeholder:text-fog-2 focus:border-signal"
              />
            </div>
            <Button onClick={runAudit} disabled={!draft.trim()}>
              <Sparkles size={14} /> Run Audit
            </Button>
          </CardBody>
        </Card>

        <GitHubMetadataCard source={draft} />

        {!report && !auditQuery.isLoading && (
          <EmptyState
            icon={<FolderGit2 size={28} />}
            title="No repository indexed yet"
            description="Enter a repository above and run an audit to see its metadata, health score, and detected technologies here."
          />
        )}

        {auditQuery.isLoading && <Skeleton className="h-40 w-full" />}

        {report && (
          <div className="grid grid-cols-1 gap-6 lg:grid-cols-2">
            <Card>
              <CardHeader>
                <CardTitle>Repository Overview</CardTitle>
              </CardHeader>
              <CardBody>
                <dl className="grid grid-cols-2 gap-y-3 text-sm">
                  <dt className="text-fog-2">Name</dt>
                  <dd className="text-fog-0">{shortRepoName(report.repo_source)}</dd>
                  <dt className="text-fog-2">Source</dt>
                  <dd className="truncate text-fog-0" title={report.repo_source}>
                    {report.repo_source}
                  </dd>
                  <dt className="text-fog-2">Repo ID</dt>
                  <dd className="font-mono-nums text-fog-0">{report.repo_id}</dd>
                  <dt className="text-fog-2">Files scanned</dt>
                  <dd className="font-mono-nums text-fog-0">{report.files_scanned}</dd>
                  <dt className="text-fog-2">Chunks indexed</dt>
                  <dd className="font-mono-nums text-fog-0">{report.chunks_indexed}</dd>
                  <dt className="text-fog-2">First run</dt>
                  <dd className="text-fog-0">{report.is_first_run ? "Yes" : "No — history available"}</dd>
                  <dt className="text-fog-2">Total directories</dt>
                  <dd className="font-mono-nums text-fog-0">{report.repo_profile.total_directories}</dd>
                  <dt className="text-fog-2">Primary language</dt>
                  <dd className="text-fog-0">{report.repo_profile.primary_language ?? "—"}</dd>
                  <dt className="text-fog-2">Package manager</dt>
                  <dd className="text-fog-0">{report.repo_profile.package_manager ?? "Not detected"}</dd>
                  <dt className="text-fog-2">Framework(s) detected</dt>
                  <dd className="text-fog-0">
                    {report.repo_profile.frameworks.length ? report.repo_profile.frameworks.join(", ") : "Not detected"}
                  </dd>
                  <dt className="text-fog-2">File types detected</dt>
                  <dd className="text-fog-0">{Array.from(languages).join(", ") || "—"}</dd>
                </dl>
              </CardBody>
            </Card>

            <Card>
              <CardHeader>
                <CardTitle>Documentation Coverage</CardTitle>
              </CardHeader>
              <CardBody className="space-y-2">
                {report.doc_suggestions.length === 0 ? (
                  <p className="text-sm text-fog-2">No documentation gaps detected.</p>
                ) : (
                  report.doc_suggestions.slice(0, 6).map((d, i) => (
                    <div key={i} className="rounded-lg border border-hairline bg-panel px-3 py-2 text-xs">
                      <p className="font-mono-nums text-fog-2">
                        {d.file}
                        {d.line ? `:${d.line}` : ""} · {d.kind.replaceAll("_", " ")}
                      </p>
                      <p className="mt-1 text-fog-1">{d.rationale}</p>
                    </div>
                  ))
                )}
              </CardBody>
            </Card>
          </div>
        )}

        {report && report.architecture_explanation && (
          <Card>
            <CardHeader>
              <CardTitle>Architecture Overview</CardTitle>
            </CardHeader>
            <CardBody>
              <p className="text-sm leading-relaxed text-fog-1">{report.architecture_explanation}</p>
            </CardBody>
          </Card>
        )}
      </div>
    </>
  );
}
