import { describe, it, expect, vi, beforeEach } from "vitest";
import { api, ApiError } from "../lib/api";

function mockFetchOnce(body: unknown, ok = true, status = 200) {
  vi.stubGlobal(
    "fetch",
    vi.fn().mockResolvedValue({
      ok,
      status,
      statusText: ok ? "OK" : "Error",
      json: async () => body,
    })
  );
}

describe("api client", () => {
  beforeEach(() => {
    vi.unstubAllGlobals();
  });

  it("startAudit posts to /api/audits with the source", async () => {
    mockFetchOnce({ run_id: "run_123", status: "running" });
    const result = await api.startAudit("https://github.com/org/repo");
    expect(result.run_id).toBe("run_123");

    const [url, init] = (fetch as ReturnType<typeof vi.fn>).mock.calls[0];
    expect(url).toBe("/api/audits");
    expect(init.method).toBe("POST");
    expect(JSON.parse(init.body)).toEqual({ source: "https://github.com/org/repo" });
  });

  it("listAudits performs a GET to /api/audits", async () => {
    mockFetchOnce([{ run_id: "r1", repo_id: null, repo_source: "x", ts: 1, status: "done" }]);
    const result = await api.listAudits();
    expect(result).toHaveLength(1);
    const [url] = (fetch as ReturnType<typeof vi.fn>).mock.calls[0];
    expect(url).toBe("/api/audits");
  });

  it("getAuditStatus hits the correct run-scoped URL", async () => {
    mockFetchOnce({ run_id: "run_1", status: "done", percent: 100, stages: [] });
    await api.getAuditStatus("run_1");
    const [url] = (fetch as ReturnType<typeof vi.fn>).mock.calls[0];
    expect(url).toBe("/api/audits/run_1/status");
  });

  it("compareRuns URL-encodes run ids", async () => {
    mockFetchOnce({});
    await api.compareRuns("run a", "run b");
    const [url] = (fetch as ReturnType<typeof vi.fn>).mock.calls[0];
    expect(url).toBe("/api/audits/compare?run_a=run%20a&run_b=run%20b");
  });

  it("proposeFixes posts max_findings and fingerprints", async () => {
    mockFetchOnce([]);
    await api.proposeFixes("run_1", { max_findings: 3, fingerprints: ["abc"] });
    const [url, init] = (fetch as ReturnType<typeof vi.fn>).mock.calls[0];
    expect(url).toBe("/api/audits/run_1/fixes");
    expect(JSON.parse(init.body)).toEqual({ max_findings: 3, fingerprints: ["abc"] });
  });

  it("reportUrl builds the right export URL per format", () => {
    expect(api.reportUrl("run_1", "md")).toBe("/api/audits/run_1/report.md");
    expect(api.reportUrl("run_1", "pdf")).toBe("/api/audits/run_1/report.pdf");
  });

  it("throws ApiError with the response detail on a non-ok response", async () => {
    mockFetchOnce({ detail: "Something went wrong" }, false, 404);
    await expect(api.getAudit("missing")).rejects.toMatchObject({
      status: 404,
      message: "Something went wrong",
    });
  });

  it("ApiError is thrown as an instance of ApiError", async () => {
    mockFetchOnce({ detail: "nope" }, false, 500);
    try {
      await api.getAudit("x");
      expect.unreachable();
    } catch (err) {
      expect(err).toBeInstanceOf(ApiError);
    }
  });

  it("getFileContent URL-encodes the file path", async () => {
    mockFetchOnce({ run_id: "r", path: "src/a b.py", language: "python", content: "", findings: [] });
    await api.getFileContent("r", "src/a b.py");
    const [url] = (fetch as ReturnType<typeof vi.fn>).mock.calls[0];
    expect(url).toBe("/api/audits/r/file?path=src%2Fa%20b.py");
  });
});
