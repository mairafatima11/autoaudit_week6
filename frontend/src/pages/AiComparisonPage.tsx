import { useState } from "react";
import { useMutation, useQuery } from "@tanstack/react-query";
import { AlertCircle, Loader2, Split } from "lucide-react";
import { TopBar } from "../components/TopBar";
import { Card, CardBody, CardHeader, CardTitle } from "../components/ui/Card";
import { Badge, Button } from "../components/ui/primitives";
import { PendingWork } from "../components/PendingWork";
import { api, LONG_TIMEOUT_MS } from "../lib/api";

const PROVIDER_LABEL: Record<string, string> = { groq: "Groq · Llama 3.3 70B", gemini: "Gemini" };

export function AiComparisonPage() {
  const [prompt, setPrompt] = useState("Explain the risk of using eval() on unsanitized user input.");

  const modelsQuery = useQuery({ queryKey: ["models"], queryFn: api.availableModels });
  const compareMutation = useMutation({
    mutationFn: () => api.compareModels(prompt),
  });

  return (
    <>
      <TopBar
        title="AI Comparison"
        subtitle="Run the same prompt across every configured model and compare side by side"
      />
      <div className="space-y-6 p-8">
        <Card>
          <CardBody className="space-y-3 pt-5">
            <div className="flex flex-wrap gap-2">
              {modelsQuery.data?.providers.map((p) => (
                <Badge key={p.id} variant={p.live ? "success" : "neutral"}>
                  {PROVIDER_LABEL[p.id] ?? p.id} · {p.model} · {p.live ? "live" : "mock"}
                </Badge>
              ))}
            </div>
            <textarea
              value={prompt}
              onChange={(e) => setPrompt(e.target.value)}
              rows={3}
              className="w-full rounded-lg border border-hairline bg-panel px-3 py-2.5 text-sm text-fog-0 placeholder:text-fog-2 focus:border-signal"
              placeholder="Ask something about a finding, a code snippet, or a design decision…"
            />
            <div className="flex justify-end">
              <Button onClick={() => compareMutation.mutate()} disabled={compareMutation.isPending || !prompt.trim()}>
                {compareMutation.isPending ? <Loader2 size={14} className="animate-spin" /> : <Split size={14} />}
                Run Comparison
              </Button>
            </div>
          </CardBody>
        </Card>

        {compareMutation.isPending && (
          <Card>
            <CardBody className="pt-5">
              <PendingWork
                label="Running the prompt against every configured provider…"
                expectedSeconds={20}
                timeoutSeconds={LONG_TIMEOUT_MS / 1000}
              />
            </CardBody>
          </Card>
        )}

        {/* This page previously rendered nothing at all on failure: the
            spinner simply stopped and the user was left guessing. */}
        {compareMutation.isError && (
          <div className="flex items-start gap-3 rounded-lg border border-critical/30 bg-critical-dim px-4 py-3">
            <AlertCircle size={16} className="mt-0.5 shrink-0 text-critical" />
            <div className="text-sm">
              <p className="font-medium text-critical">Comparison failed</p>
              <p className="mt-0.5 text-fog-1">{(compareMutation.error as Error).message}</p>
              <Button
                size="sm"
                variant="secondary"
                className="mt-2"
                onClick={() => compareMutation.mutate()}
              >
                Try again
              </Button>
            </div>
          </div>
        )}

        {compareMutation.data && (
          <>
            <div className="grid grid-cols-1 gap-5 md:grid-cols-2">
              {compareMutation.data.results.map((r) => (
                <Card key={r.provider}>
                  <CardHeader>
                    <CardTitle>{PROVIDER_LABEL[r.provider] ?? r.provider}</CardTitle>
                    {r.error ? (
                      <Badge variant="critical">error</Badge>
                    ) : (
                      <Badge variant="signal">{Math.round(r.confidence * 100)}% confidence</Badge>
                    )}
                  </CardHeader>
                  <CardBody className="space-y-3">
                    {r.error ? (
                      <p className="text-sm text-critical">{r.error}</p>
                    ) : (
                      <p className="text-sm leading-relaxed text-fog-1">{r.response}</p>
                    )}
                    <div className="flex gap-4 font-mono-nums text-xs text-fog-2">
                      <span>{r.latency_ms.toFixed(0)} ms</span>
                      <span>~{r.token_estimate} tokens</span>
                    </div>
                  </CardBody>
                </Card>
              ))}
            </div>

            <Card>
              <CardHeader>
                <CardTitle>Merged Result</CardTitle>
                <Badge variant={compareMutation.data.agreement ? "success" : "warning"}>
                  {compareMutation.data.agreement ? "Agreement" : "Disagreement"}
                </Badge>
              </CardHeader>
              <CardBody className="space-y-3">
                <p className="text-sm text-fog-1">{compareMutation.data.differences}</p>
                <div className="rounded-lg border border-hairline-soft bg-panel-raised px-4 py-3 text-sm text-fog-0">
                  {compareMutation.data.merged_answer}
                </div>
                {compareMutation.data.reasoning_summary && (
                  <div>
                    <p className="mb-1 text-xs font-medium uppercase tracking-wider text-fog-2">Reasoning Summary</p>
                    <p className="text-xs text-fog-2">{compareMutation.data.reasoning_summary}</p>
                  </div>
                )}
              </CardBody>
            </Card>
          </>
        )}
      </div>
    </>
  );
}
