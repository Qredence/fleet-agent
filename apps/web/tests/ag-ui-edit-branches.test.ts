import { createRequire } from "node:module";
import { dirname, join } from "node:path";
import { describe, expect, it, vi } from "vitest";

// Exercise the installed patched runtime, rather than duplicating its algorithm.
const require = createRequire(import.meta.url);
const corePath = join(
  dirname(require.resolve("@assistant-ui/react-ag-ui")),
  "runtime/AgUiThreadRuntimeCore.js",
);
const { AgUiThreadRuntimeCore } = await import(/* @vite-ignore */ corePath);
function core() {
  return new AgUiThreadRuntimeCore({
    agent: { runAgent: vi.fn(), abortRun: vi.fn() },
    logger: { error: vi.fn(), warn: vi.fn(), info: vi.fn(), debug: vi.fn() },
    showThinking: false,
    notifyUpdate: vi.fn(),
  });
}
const message = (text: string, parentId: string | null = null) => ({
  role: "user",
  content: [{ type: "text", text }],
  parentId,
  startRun: false,
});
describe("edited and queued branch ownership", () => {
  it("preserves the original branch and creates an edited sibling root", async () => {
    const runtime = core();
    await runtime.append(message("Cedar 100"));
    const original = runtime.getMessages()[0];
    await runtime.append({
      ...message("original answer", original.id),
      role: "assistant",
    });
    await runtime.edit({ ...message("Larch 900"), sourceId: original.id });
    expect(
      runtime.getMessages().map((m: { content: unknown }) => m.content),
    ).toEqual([[{ type: "text", text: "Larch 900" }]]);
    const entries = runtime.getMessageRepository().messages;
    expect(
      entries.find(
        (e: { message: { id: string } }) => e.message.id === original.id,
      ),
    ).toBeDefined();
    expect(
      entries.filter((e: { parentId: string | null }) => e.parentId === null),
    ).toHaveLength(2);
  });
  it("still resolves an ordinary queued null parent to the current head", async () => {
    const runtime = core();
    await runtime.append(message("first"));
    const first = runtime.getMessages()[0];
    await runtime.append(message("queued continuation"));
    const last = runtime.getMessageRepository().messages.at(-1);
    expect(last.parentId).toBe(first.id);
  });
});
