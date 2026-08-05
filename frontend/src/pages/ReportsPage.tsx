import { useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { Download, FileOutput, FileJson, FileText, FileCode, FileType } from "lucide-react";
import { TopBar } from "../components/TopBar";
import { Card, CardBody, CardHeader, CardTitle } from "../components/ui/Card";
import { Button, EmptyState } from "../components/ui/primitives";
import { api } from "../lib/api";
import { useRunContext } from "../lib/RunContext";

type Format = "md" | "html" | "json" | "pdf";

export function ReportsPage() {
  const { activeRunId } = useRunContext();
  const [format, setFormat] = useState<Format>("md");

  const auditQuery = useQuery({
    queryKey: ["audit", activeRunId],
    queryFn: () => api.getAudit(activeRunId!),
    enabled: !!activeRunId,
  });

  const previewQuery = useQuery({
    queryKey: ["report-preview", activeRunId, format],
    queryFn: async () => {
      const res = await fetch(api.reportUrl(activeRunId!, format));
      return format === "json" ? JSON.stringify(await res.json(), null, 2) : res.text();
    },
    enabled: !!activeRunId && format !== "pdf",
  });

  if (!activeRunId) {
    return (
      <>
        <TopBar title="Reports" />
        <div className="p-8">
          <EmptyState icon={<FileOutput size={28} />} title="No report yet" description="Run an audit to generate an exportable report." />
        </div>
      </>
    );
  }

  const formats: { id: Format; label: string; icon: typeof FileText }[] = [
    { id: "md", label: "Markdown", icon: FileText },
    { id: "html", label: "HTML", icon: FileCode },
    { id: "json", label: "JSON", icon: FileJson },
    { id: "pdf", label: "PDF", icon: FileType },
  ];

  return (
    <>
      <TopBar
        title="Reports"
        subtitle={auditQuery.data ? `Run ${auditQuery.data.report.run_id}` : undefined}
        right={
          <a href={api.reportUrl(activeRunId, format)} download={`autoaudit-report.${format}`}>
            <Button>
              <Download size={14} /> Download
            </Button>
          </a>
        }
      />
      <div className="space-y-6 p-8">
        <div className="flex gap-2">
          {formats.map(({ id, label, icon: Icon }) => (
            <button
              key={id}
              onClick={() => setFormat(id)}
              className={`flex items-center gap-2 rounded-lg border px-3.5 py-2 text-sm font-medium transition-colors ${
                format === id ? "border-signal bg-signal/10 text-signal-glow" : "border-hairline text-fog-1 hover:text-fog-0"
              }`}
            >
              <Icon size={14} /> {label}
            </button>
          ))}
        </div>

        <Card>
          <CardHeader>
            <CardTitle>Preview</CardTitle>
          </CardHeader>
          <CardBody>
            {format === "html" ? (
              <iframe
                title="report-html-preview"
                srcDoc={previewQuery.data ?? ""}
                className="h-[600px] w-full rounded-lg border border-hairline-soft bg-white"
              />
            ) : format === "pdf" ? (
              <iframe
                title="report-pdf-preview"
                src={api.reportUrl(activeRunId, "pdf")}
                className="h-[600px] w-full rounded-lg border border-hairline-soft bg-white"
              />
            ) : (
              <pre className="max-h-[600px] overflow-auto whitespace-pre-wrap rounded-lg border border-hairline-soft bg-ink p-4 font-mono-nums text-xs leading-relaxed text-fog-1">
                {previewQuery.data ?? "Loading…"}
              </pre>
            )}
          </CardBody>
        </Card>
      </div>
    </>
  );
}
