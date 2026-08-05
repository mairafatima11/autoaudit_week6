import { useEffect, useRef } from "react";
import { PrismLight as SyntaxHighlighter } from "react-syntax-highlighter";
import python from "react-syntax-highlighter/dist/esm/languages/prism/python";
import javascript from "react-syntax-highlighter/dist/esm/languages/prism/javascript";
import typescript from "react-syntax-highlighter/dist/esm/languages/prism/typescript";
import jsx from "react-syntax-highlighter/dist/esm/languages/prism/jsx";
import tsx from "react-syntax-highlighter/dist/esm/languages/prism/tsx";
import json from "react-syntax-highlighter/dist/esm/languages/prism/json";
import yaml from "react-syntax-highlighter/dist/esm/languages/prism/yaml";
import bash from "react-syntax-highlighter/dist/esm/languages/prism/bash";
import go from "react-syntax-highlighter/dist/esm/languages/prism/go";
import java from "react-syntax-highlighter/dist/esm/languages/prism/java";
import ruby from "react-syntax-highlighter/dist/esm/languages/prism/ruby";
import php from "react-syntax-highlighter/dist/esm/languages/prism/php";
import c from "react-syntax-highlighter/dist/esm/languages/prism/c";
import cpp from "react-syntax-highlighter/dist/esm/languages/prism/cpp";
import rust from "react-syntax-highlighter/dist/esm/languages/prism/rust";
import markup from "react-syntax-highlighter/dist/esm/languages/prism/markup";
import { vscDarkPlus } from "react-syntax-highlighter/dist/esm/styles/prism";
import type { FileFindingRef } from "../lib/types";
import { SEVERITY_META } from "../lib/utils";

SyntaxHighlighter.registerLanguage("python", python);
SyntaxHighlighter.registerLanguage("javascript", javascript);
SyntaxHighlighter.registerLanguage("typescript", typescript);
SyntaxHighlighter.registerLanguage("jsx", jsx);
SyntaxHighlighter.registerLanguage("tsx", tsx);
SyntaxHighlighter.registerLanguage("json", json);
SyntaxHighlighter.registerLanguage("yaml", yaml);
SyntaxHighlighter.registerLanguage("shell", bash);
SyntaxHighlighter.registerLanguage("bash", bash);
SyntaxHighlighter.registerLanguage("go", go);
SyntaxHighlighter.registerLanguage("java", java);
SyntaxHighlighter.registerLanguage("ruby", ruby);
SyntaxHighlighter.registerLanguage("php", php);
SyntaxHighlighter.registerLanguage("c", c);
SyntaxHighlighter.registerLanguage("cpp", cpp);
SyntaxHighlighter.registerLanguage("rust", rust);
SyntaxHighlighter.registerLanguage("plaintext", markup);

const SEVERITY_BG: Record<FileFindingRef["severity"], string> = {
  high: "rgba(240, 73, 92, 0.16)",
  medium: "rgba(245, 166, 35, 0.14)",
  low: "rgba(232, 195, 77, 0.12)",
  info: "rgba(89, 185, 176, 0.12)",
};

const SEVERITY_BORDER: Record<FileFindingRef["severity"], string> = {
  high: "var(--color-critical)",
  medium: "var(--color-warning)",
  low: "var(--color-caution)",
  info: "var(--color-info)",
};

export function CodeViewer({
  content,
  language,
  findings,
  highlightLine,
  onLineClick,
}: {
  content: string;
  language: string;
  findings: FileFindingRef[];
  highlightLine?: number | null;
  onLineClick?: (line: number) => void;
}) {
  const containerRef = useRef<HTMLDivElement>(null);
  const findingsByLine = new Map<number, FileFindingRef[]>();
  findings.forEach((f) => {
    findingsByLine.set(f.line, [...(findingsByLine.get(f.line) ?? []), f]);
  });

  useEffect(() => {
    if (!highlightLine || !containerRef.current) return;
    const el = containerRef.current.querySelector(`#code-line-${highlightLine}`);
    el?.scrollIntoView({ behavior: "smooth", block: "center" });
  }, [highlightLine, content]);

  return (
    <div ref={containerRef} className="max-h-[70vh] overflow-auto rounded-lg border border-hairline-soft">
      <SyntaxHighlighter
        language={language === "text" ? "plaintext" : language}
        style={vscDarkPlus}
        showLineNumbers
        wrapLines
        lineNumberStyle={{ color: "var(--color-fog-2)", minWidth: "3em", userSelect: "none" }}
        customStyle={{ margin: 0, background: "var(--color-ink)", fontSize: "12.5px", lineHeight: 1.6 }}
        lineProps={(lineNumber: number) => {
          const lineFindings = findingsByLine.get(lineNumber);
          const isHighlighted = highlightLine === lineNumber;
          const style: React.CSSProperties = { display: "block", cursor: onLineClick ? "pointer" : "default" };
          if (lineFindings?.length) {
            const worst = lineFindings.sort((a, b) => severityRank(a.severity) - severityRank(b.severity))[0];
            style.background = SEVERITY_BG[worst.severity];
            style.borderLeft = `3px solid ${SEVERITY_BORDER[worst.severity]}`;
          }
          if (isHighlighted) {
            style.background = "rgba(76, 158, 255, 0.18)";
            style.borderLeft = "3px solid var(--color-signal)";
          }
          return {
            id: `code-line-${lineNumber}`,
            style,
            onClick: () => onLineClick?.(lineNumber),
            title: lineFindings?.length
              ? lineFindings.map((f) => `${f.title} (${Math.round(f.confidence * 100)}% confidence)`).join("; ")
              : undefined,
          };
        }}
      >
        {content}
      </SyntaxHighlighter>
    </div>
  );
}

function severityRank(s: FileFindingRef["severity"]) {
  return { high: 0, medium: 1, low: 2, info: 3 }[s];
}

export function FindingLineBadge({ severity }: { severity: FileFindingRef["severity"] }) {
  const meta = SEVERITY_META[severity];
  return <span className={`inline-block h-2 w-2 rounded-full ${meta.dot}`} />;
}
