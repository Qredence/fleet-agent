import { describe, expect, it } from "vitest";

import { formatDuration } from "@/lib/duration";

describe("formatDuration", () => {
  it("renders an em dash for a missing duration", () => {
    expect(formatDuration(undefined)).toBe("—");
    expect(formatDuration(null)).toBe("—");
  });

  it("renders raw milliseconds below one second", () => {
    expect(formatDuration(0)).toBe("0ms");
    expect(formatDuration(2)).toBe("2ms");
    expect(formatDuration(250)).toBe("250ms");
    expect(formatDuration(400)).toBe("400ms");
    expect(formatDuration(900)).toBe("900ms");
    expect(formatDuration(999)).toBe("999ms");
  });

  it("renders one-decimal seconds from one second up to a minute", () => {
    expect(formatDuration(1000)).toBe("1.0s");
    expect(formatDuration(1500)).toBe("1.5s");
    expect(formatDuration(1900)).toBe("1.9s");
    expect(formatDuration(9500)).toBe("9.5s");
    expect(formatDuration(12500)).toBe("12.5s");
    expect(formatDuration(59999)).toBe("60.0s");
  });

  it("renders whole minutes and seconds from one minute up", () => {
    expect(formatDuration(60000)).toBe("1m 0s");
    expect(formatDuration(65000)).toBe("1m 5s");
    expect(formatDuration(125000)).toBe("2m 5s");
    expect(formatDuration(3599999)).toBe("59m 59s");
  });

  // These three values previously rendered differently on each surface
  // ("12s"/"12.5s"/"12500ms" etc). Pinning them keeps the formatters converged.
  it("pins the values that the three drifted implementations disagreed on", () => {
    expect(formatDuration(250)).toBe("250ms");
    expect(formatDuration(12500)).toBe("12.5s");
    expect(formatDuration(65000)).toBe("1m 5s");
  });
});
