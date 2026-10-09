import {
  cleanup,
  fireEvent,
  render,
  screen,
  waitFor,
} from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { ArtifactsTab } from "@/features/process-panel/artifacts-tab";
import { SourcesTab } from "@/features/process-panel/sources-tab";
import type { AgentWorkspaceState } from "@/contracts/generated";
import { useWorkspaceStore } from "@/state/workspace-store";

const state: AgentWorkspaceState = {
  schemaVersion: 2,
  threadId: "t-1",
  run: {
    saveStatus: "unknown",
    id: "r-1",
    status: "completed",
    toolCallCount: 1,
  },
  steps: [],
  decisions: [],
  toolCalls: [
    {
      id: "tc-1",
      name: "search_docs",
      status: "completed",
    },
  ],
  sources: [
    {
      id: "src-1",
      title: "AG-UI — Events",
      sourceType: "web",
      uri: "https://docs.ag-ui.com/sdk/python/core/events",
      excerpt: "Deltas.",
      toolCallId: "tc-1",
    },
  ],
  artifacts: [
    {
      id: "a-1",
      name: "state-sync-notes.md",
      mediaType: "text/markdown",
      sizeBytes: 64,
      downloadUrl: "/api/artifacts/a-1",
      status: "ready",
    },
  ],
  metrics: { toolCallCount: 1 },
};

vi.mock("@/lib/env", () => ({
  API_BASE_URL: "http://localhost:8000",
  API_KEY: "acceptance-api-key",
}));
const fetchMock = vi.fn();

beforeEach(() => {
  fetchMock.mockResolvedValue(
    new Response(
      "# DSPy report\n\n**Actual Markdown content**\n\n- One useful finding\n\n[Official source](https://dspy.ai)",
      { headers: { "content-type": "text/markdown" } },
    ),
  );
  vi.stubGlobal("fetch", fetchMock);
  useWorkspaceStore.setState({
    selectedArtifactId: null,
    processPanelTab: "sources",
  });
});

afterEach(() => {
  cleanup();
  vi.unstubAllGlobals();
  fetchMock.mockReset();
});

describe("SourcesTab — originating tool", () => {
  it("shows which tool produced the source", () => {
    render(
      <SourcesTab
        sources={state.sources}
        toolNamesById={new Map([["tc-1", "search_docs"]])}
      />,
    );
    expect(screen.getByText(/via search_docs/)).toBeInTheDocument();
  });
});

describe("ArtifactsTab — selection + download URL", () => {
  it("renders the actual Markdown content for the selected artifact", async () => {
    render(
      <ArtifactsTab artifacts={state.artifacts} selectedArtifactId="a-1" />,
    );

    expect(
      await screen.findByRole("heading", { name: "DSPy report" }),
    ).toBeInTheDocument();
    expect(screen.getByText("Actual Markdown content")).toBeInTheDocument();
    expect(screen.getByText("One useful finding")).toBeInTheDocument();

    const source = screen.getByRole("link", { name: "Official source" });
    expect(source).toHaveAttribute("href", "https://dspy.ai/");
    expect(source).toHaveAttribute("target", "_blank");
    expect(source).toHaveAttribute("rel", "noopener noreferrer");
    expect(fetchMock).toHaveBeenCalledWith(
      "http://localhost:8000/api/artifacts/a-1",
      expect.objectContaining({
        headers: expect.objectContaining({
          Accept: "text/plain, text/markdown;q=0.9",
        }),
      }),
    );
  });

  it("downloads controlled URLs with authentication and the artifact filename", async () => {
    const create = vi.fn(() => "blob:test-download");
    vi.stubGlobal("URL", { createObjectURL: create, revokeObjectURL: vi.fn() });
    const click = vi
      .spyOn(HTMLAnchorElement.prototype, "click")
      .mockImplementation(() => {});
    render(<ArtifactsTab artifacts={state.artifacts} />);
    fireEvent.click(
      screen.getByRole("button", {
        name: "download artifact: state-sync-notes.md",
      }),
    );
    await waitFor(() => expect(click).toHaveBeenCalled());
    expect(fetchMock).toHaveBeenCalledWith(
      "http://localhost:8000/api/artifacts/a-1",
      {
        headers: { "X-API-Key": "acceptance-api-key" },
      },
    );
    expect(create).toHaveBeenCalledWith(expect.any(Blob));
    expect((click.mock.instances[0] as HTMLAnchorElement).download).toBe("state-sync-notes.md");
    click.mockRestore();
  });

  it("shows a download failure without changing ready artifact truth", async () => {
    fetchMock.mockResolvedValueOnce(new Response("", { status: 503 }));
    render(<ArtifactsTab artifacts={state.artifacts} />);
    fireEvent.click(
      screen.getByRole("button", {
        name: "download artifact: state-sync-notes.md",
      }),
    );
    expect(await screen.findByRole("alert")).toHaveTextContent(
      "could not be downloaded",
    );
    expect(screen.getByText("Ready")).toBeInTheDocument();
  });

  it("highlights the selected artifact", () => {
    render(
      <ArtifactsTab artifacts={state.artifacts} selectedArtifactId="a-1" />,
    );
    const card = screen.getByRole("article", {
      name: "artifact: state-sync-notes.md",
    });
    expect(card).toHaveAttribute("aria-current", "true");
    expect(card.className).toContain("border-primary/50");
  });

  it("does not highlight others", () => {
    render(
      <ArtifactsTab artifacts={state.artifacts} selectedArtifactId="a-999" />,
    );
    expect(
      screen.getByRole("article", { name: "artifact: state-sync-notes.md" }),
    ).not.toHaveAttribute("aria-current");
  });
});

describe("workspace store — artifact selection", () => {
  it("tracks selection transiently", () => {
    useWorkspaceStore.getState().setSelectedArtifactId("a-1");
    expect(useWorkspaceStore.getState().selectedArtifactId).toBe("a-1");

    const persisted = JSON.parse(
      localStorage.getItem("fleet-agent-workspace") ?? "{}",
    ) as { state: Record<string, unknown> };
    expect(persisted.state.selectedArtifactId).toBeUndefined();
  });
});
