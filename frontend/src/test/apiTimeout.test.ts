import { describe, it, expect, vi, beforeEach, afterEach } from "vitest";
import { api, ApiTimeoutError, DEFAULT_TIMEOUT_MS, LONG_TIMEOUT_MS } from "../lib/api";

/**
 * `fetch` has no timeout of its own. Without an AbortController the UI sits
 * on a spinner indefinitely when the backend stalls, which is exactly how
 * "Generate Fixes" and "Run Comparison" appeared to hang — the user had no
 * way to distinguish slow from dead.
 */
describe("api request timeouts", () => {
  beforeEach(() => vi.useFakeTimers());
  afterEach(() => vi.useRealTimers());

  function stubNeverResolving() {
    const seen: { signal?: AbortSignal } = {};
    vi.stubGlobal(
      "fetch",
      vi.fn((_url: string, init?: RequestInit) => {
        seen.signal = init?.signal ?? undefined;
        return new Promise((_resolve, reject) => {
          init?.signal?.addEventListener("abort", () =>
            reject(new DOMException("Aborted", "AbortError")),
          );
        });
      }),
    );
    return seen;
  }

  it("passes an abort signal on every request", async () => {
    const seen = stubNeverResolving();
    const pending = api.listAudits().catch(() => undefined);
    expect(seen.signal).toBeInstanceOf(AbortSignal);
    await vi.advanceTimersByTimeAsync(DEFAULT_TIMEOUT_MS + 10);
    await pending;
  });

  it("rejects with a readable timeout error rather than hanging", async () => {
    stubNeverResolving();
    const pending = api.listAudits();
    const assertion = expect(pending).rejects.toBeInstanceOf(ApiTimeoutError);
    await vi.advanceTimersByTimeAsync(DEFAULT_TIMEOUT_MS + 10);
    await assertion;
  });

  it("explains the wait and suggests retrying", async () => {
    stubNeverResolving();
    const pending = api.listAudits().then(
      () => null,
      (e: Error) => e,
    );
    await vi.advanceTimersByTimeAsync(DEFAULT_TIMEOUT_MS + 10);
    const err = await pending;
    expect(err).not.toBeNull();
    expect(err!.message).toMatch(/did not respond within \d+s/);
    expect(err!.message).toMatch(/try again/i);
  });

  it("does not time out model-backed endpoints at the short default", async () => {
    // Fix proposals and model comparison legitimately take longer, and the
    // client must not cut them off before the server's own budget applies.
    stubNeverResolving();
    let settled = false;
    const pending = api.proposeFixes("run_1", {}).catch(() => {
      settled = true;
    });

    await vi.advanceTimersByTimeAsync(DEFAULT_TIMEOUT_MS + 1_000);
    expect(settled).toBe(false);

    await vi.advanceTimersByTimeAsync(LONG_TIMEOUT_MS);
    await pending;
    expect(settled).toBe(true);
  });

  it("gives the comparison endpoint the long ceiling too", async () => {
    stubNeverResolving();
    let settled = false;
    const pending = api.compareModels("prompt").catch(() => {
      settled = true;
    });
    await vi.advanceTimersByTimeAsync(DEFAULT_TIMEOUT_MS + 1_000);
    expect(settled).toBe(false);
    await vi.advanceTimersByTimeAsync(LONG_TIMEOUT_MS);
    await pending;
    expect(settled).toBe(true);
  });

  it("leaves the client ceiling above the server's own budget", () => {
    // The server bounds fix batches at 90s and interactive model calls at
    // 45s. The client must lose that race so the user sees the server's
    // specific message instead of a generic client timeout.
    expect(LONG_TIMEOUT_MS).toBeGreaterThan(90_000);
  });

  it("clears its timer when a request succeeds", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn(async () => ({ ok: true, status: 200, json: async () => [] })),
    );
    const clearSpy = vi.spyOn(globalThis, "clearTimeout");
    await api.listAudits();
    expect(clearSpy).toHaveBeenCalled();
  });
});
