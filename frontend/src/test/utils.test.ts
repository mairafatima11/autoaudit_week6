import { describe, it, expect } from "vitest";
import { cn, formatRelativeTime, formatTimestamp, scoreColor, shortRepoName, SEVERITY_META } from "../lib/utils";

describe("cn", () => {
  it("joins truthy class names", () => {
    const isHidden = false;
    expect(cn("a", "b", isHidden && "c", undefined, "d")).toBe("a b d");
  });

  it("returns empty string for no args", () => {
    expect(cn()).toBe("");
  });
});

describe("SEVERITY_META", () => {
  it("has an entry for every severity level", () => {
    expect(Object.keys(SEVERITY_META).sort()).toEqual(["high", "info", "low", "medium"]);
  });

  it("labels are human readable", () => {
    expect(SEVERITY_META.high.label).toBe("High");
    expect(SEVERITY_META.info.label).toBe("Info");
  });
});

describe("formatRelativeTime", () => {
  it("returns 'just now' for very recent timestamps", () => {
    const now = Date.now() / 1000;
    expect(formatRelativeTime(now)).toBe("just now");
  });

  it("returns seconds for < 1 minute", () => {
    const tenSecondsAgo = Date.now() / 1000 - 10;
    expect(formatRelativeTime(tenSecondsAgo)).toMatch(/^\d+s ago$/);
  });

  it("returns minutes for < 1 hour", () => {
    const fiveMinAgo = Date.now() / 1000 - 5 * 60;
    expect(formatRelativeTime(fiveMinAgo)).toMatch(/^\d+m ago$/);
  });

  it("returns hours for < 1 day", () => {
    const threeHoursAgo = Date.now() / 1000 - 3 * 3600;
    expect(formatRelativeTime(threeHoursAgo)).toMatch(/^\d+h ago$/);
  });

  it("returns days for >= 1 day", () => {
    const twoDaysAgo = Date.now() / 1000 - 2 * 86400;
    expect(formatRelativeTime(twoDaysAgo)).toMatch(/^\d+d ago$/);
  });
});

describe("formatTimestamp", () => {
  it("produces a non-empty formatted string", () => {
    const result = formatTimestamp(1700000000);
    expect(typeof result).toBe("string");
    expect(result.length).toBeGreaterThan(0);
  });
});

describe("scoreColor", () => {
  it("returns success color for high scores", () => {
    expect(scoreColor(95)).toBe("text-success");
    expect(scoreColor(80)).toBe("text-success");
  });

  it("returns warning color for medium scores", () => {
    expect(scoreColor(70)).toBe("text-warning");
    expect(scoreColor(60)).toBe("text-warning");
  });

  it("returns critical color for low scores", () => {
    expect(scoreColor(59)).toBe("text-critical");
    expect(scoreColor(0)).toBe("text-critical");
  });
});

describe("shortRepoName", () => {
  it("extracts repo name from a git URL", () => {
    expect(shortRepoName("https://github.com/psf/requests.git")).toBe("requests");
  });

  it("extracts repo name from a URL without .git suffix", () => {
    expect(shortRepoName("https://github.com/psf/requests")).toBe("requests");
  });

  it("extracts the last path segment for local paths", () => {
    expect(shortRepoName("/home/user/projects/my-app")).toBe("my-app");
  });

  it("handles a trailing slash", () => {
    expect(shortRepoName("/home/user/projects/my-app/")).toBe("my-app");
  });

  it("falls back to the cleaned string for a bare name", () => {
    expect(shortRepoName("my-repo")).toBe("my-repo");
  });
});
