import { clsx, type ClassValue } from "clsx";
import type { Severity } from "./types";

export function cn(...inputs: ClassValue[]) {
  return clsx(inputs);
}

export const SEVERITY_META: Record<Severity, { label: string; color: string; dim: string; dot: string }> = {
  high: { label: "High", color: "text-critical", dim: "bg-critical-dim", dot: "bg-critical" },
  medium: { label: "Medium", color: "text-warning", dim: "bg-warning-dim", dot: "bg-warning" },
  low: { label: "Low", color: "text-caution", dim: "bg-caution-dim", dot: "bg-caution" },
  info: { label: "Info", color: "text-info", dim: "bg-info-dim", dot: "bg-info" },
};

export function formatRelativeTime(unixSeconds: number): string {
  const deltaMs = Date.now() - unixSeconds * 1000;
  const seconds = Math.floor(deltaMs / 1000);
  if (seconds < 5) return "just now";
  if (seconds < 60) return `${seconds}s ago`;
  const minutes = Math.floor(seconds / 60);
  if (minutes < 60) return `${minutes}m ago`;
  const hours = Math.floor(minutes / 60);
  if (hours < 24) return `${hours}h ago`;
  const days = Math.floor(hours / 24);
  return `${days}d ago`;
}

export function formatTimestamp(unixSeconds: number): string {
  return new Date(unixSeconds * 1000).toLocaleString(undefined, {
    month: "short",
    day: "numeric",
    hour: "2-digit",
    minute: "2-digit",
  });
}

export function scoreColor(score: number): string {
  if (score >= 80) return "text-success";
  if (score >= 60) return "text-warning";
  return "text-critical";
}

export function shortRepoName(source: string): string {
  const cleaned = source.replace(/\.git$/, "").replace(/\/$/, "");
  const parts = cleaned.split("/");
  return parts[parts.length - 1] || cleaned;
}
