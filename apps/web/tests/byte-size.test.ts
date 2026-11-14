import { describe, expect, it } from "vitest";

import { formatByteSize } from "@/lib/byte-size";

describe("formatByteSize", () => {
  it("returns null for a missing size", () => {
    expect(formatByteSize(undefined)).toBeNull();
    expect(formatByteSize(null)).toBeNull();
  });

  it("renders exact bytes below one kibibyte", () => {
    expect(formatByteSize(0)).toBe("0 B");
    expect(formatByteSize(1)).toBe("1 B");
    expect(formatByteSize(512)).toBe("512 B");
    expect(formatByteSize(1023)).toBe("1023 B");
  });

  it("renders one-decimal kibibytes from one kibibyte up", () => {
    expect(formatByteSize(1024)).toBe("1.0 KB");
    expect(formatByteSize(1025)).toBe("1.0 KB");
    expect(formatByteSize(2048)).toBe("2.0 KB");
    expect(formatByteSize(1048064)).toBe("1023.5 KB");
  });

  it("switches to megabytes before the kibibyte branch can print 1024.0 KB", () => {
    // 1048575 bytes used to render "1024.0 KB", which reads as a full MB but
    // is labelled KB. Choosing the unit from the rounded value fixes it.
    expect(formatByteSize(1048524)).toBe("1023.9 KB");
    expect(formatByteSize(1048525)).toBe("1.0 MB");
    expect(formatByteSize(1048575)).toBe("1.0 MB");
    expect(formatByteSize(1048576)).toBe("1.0 MB");
  });

  it("renders one-decimal megabytes", () => {
    expect(formatByteSize(1572864)).toBe("1.5 MB");
    expect(formatByteSize(64 * 1024 * 1024)).toBe("64.0 MB");
  });

  // The process panel test pins this reading; keep the shared formatter on it.
  it("pins 2048 bytes as 2.0 KB", () => {
    expect(formatByteSize(2048)).toBe("2.0 KB");
  });
});
