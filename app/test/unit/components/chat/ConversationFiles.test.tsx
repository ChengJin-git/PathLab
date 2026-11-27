import React from "react";
import {
  act,
  cleanup,
  fireEvent,
  render,
  screen,
  waitFor,
  within,
} from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import {
  ConversationFilesProvider,
  ConversationFilesPanel,
  ConversationFilesButton,
  FileReferenceButton,
} from "@renderer/components/chat/ConversationFiles";
import {
  conversationFiles,
  previewWorkbenchFile,
  readWorkbenchMedia,
  referenceResearchPath,
  indexResearchFiles,
  readWorkbenchPage,
} from "@renderer/api/workbench";
import { safePreviewHtml } from "@renderer/components/chat/FilePreviewContent";
import i18n from "@renderer/i18n";

vi.mock("@renderer/api/workbench", () => ({
  conversationFiles: vi.fn(),
  previewWorkbenchFile: vi.fn(),
  readWorkbenchMedia: vi.fn(),
  referenceResearchPath: vi.fn(),
  indexResearchFiles: vi.fn(),
  downloadWorkbenchFile: vi.fn(),
  readWorkbenchPage: vi.fn(),
}));
const file = { kind: "file" as const, id: "file1", name: "findings.md" };
function fixture(id = "chat1") {
  return (
    <ConversationFilesProvider
      conversationId={id}
      userId="owner"
      workspaceId={null}
      sessions={[]}
      onReference={vi.fn()}
    >
      <ConversationFilesButton />
      <FileReferenceButton file={file} />
      <ConversationFilesPanel />
    </ConversationFilesProvider>
  );
}
function mount(id = "chat1") {
  const client = new QueryClient({
    defaultOptions: { queries: { retry: false } },
  });
  const view = render(
    <QueryClientProvider client={client}>{fixture(id)}</QueryClientProvider>,
  );
  return {
    ...view,
    client,
    changeConversation: (next: string) =>
      view.rerender(
        <QueryClientProvider client={client}>
          {fixture(next)}
        </QueryClientProvider>,
      ),
  };
}
beforeEach(async () => {
  Object.defineProperty(window, "innerWidth", {
    value: 1440,
    configurable: true,
  });
  await i18n.changeLanguage("en-US");
  vi.mocked(conversationFiles)
    .mockReset()
    .mockResolvedValue({ items: [file], next_cursor: null });
  vi.mocked(previewWorkbenchFile).mockReset().mockResolvedValue({
    file_id: file.id,
    name: file.name,
    size: 28,
    revision: "1",
    kind: "markdown",
    content: "# Measured results\nAUC: 0.81",
    truncated: false,
  });
  vi.mocked(indexResearchFiles)
    .mockReset()
    .mockResolvedValue({ status: "indexing" });
  vi.mocked(referenceResearchPath).mockReset();
});
afterEach(cleanup);

describe("conversation files workspace", () => {
  it('keeps zoom menus inside fullscreen and returns to the fitted sidebar without remounting', async () => {
    vi.mocked(previewWorkbenchFile).mockResolvedValue({file_id:file.id,name:'report.pdf',size:20,revision:'1',kind:'pdf',
      page_count:1,page_width:720,page_height:960,first_page:'data:image/png;base64,AA==',truncated:false});
    mount();
    fireEvent.click(screen.getByRole('button',{name:'@findings.md'}));
    await screen.findByRole('img');
    fireEvent.click(screen.getByRole('button',{name:'Expand to full screen'}));
    const dialog=await screen.findByRole('dialog');
    fireEvent.click(within(dialog).getByRole('button',{name:'Preview zoom'}));
    const option=await screen.findByRole('option',{name:'150%'});
    expect(dialog).toContainElement(option);
    fireEvent.click(option);
    expect(screen.getByRole('dialog')).toBeVisible();
    expect(screen.getByRole('img')).toHaveStyle({width:'1080px'});
    fireEvent.click(screen.getByRole('button',{name:'Preview zoom'}));
    fireEvent.click(await screen.findByRole('option',{name:'Fit page'}));
    fireEvent.click(screen.getByRole('button',{name:'Exit full screen'}));
    await waitFor(()=>expect(screen.queryByRole('dialog')).not.toBeInTheDocument());
    expect(screen.getByRole('button',{name:'Preview zoom'})).toHaveTextContent('Fit page');
    expect(screen.getByRole('img').style.width).toBe('');
    expect(previewWorkbenchFile).toHaveBeenCalledOnce();
    expect(readWorkbenchPage).not.toHaveBeenCalled();
  });
  it("loads only metadata on open, previews on click, expands full screen and returns", async () => {
    mount();
    expect(conversationFiles).not.toHaveBeenCalled();
    expect(previewWorkbenchFile).not.toHaveBeenCalled();
    fireEvent.click(screen.getByRole("button", { name: "Conversation files" }));
    fireEvent.click(await screen.findByRole("button", { name: "findings.md" }));
    expect(
      await screen.findByRole("heading", { name: "Measured results" }),
    ).toBeInTheDocument();
    fireEvent.click(
      screen.getByRole("button", { name: "Expand to full screen" }),
    );
    const fullscreen = await screen.findByRole("dialog");
    expect(
      await within(fullscreen).findByRole("heading", {
        name: "Measured results",
      }),
    ).toBeInTheDocument();
    fireEvent.click(
      within(fullscreen).getByRole("button", { name: "Exit full screen" }),
    );
    await waitFor(() =>
      expect(screen.queryByRole("dialog")).not.toBeInTheDocument(),
    );
    expect(
      await screen.findByRole("heading", { name: "Measured results" }),
    ).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "Close file preview" }));
    expect(screen.queryByRole("complementary")).not.toBeInTheDocument();
    expect(previewWorkbenchFile).toHaveBeenCalledOnce();
  });
  it("opens a message attachment directly and drops preview state when changing conversations", async () => {
    const view = mount();
    fireEvent.click(screen.getByRole("button", { name: "@findings.md" }));
    expect(
      await screen.findByRole("heading", { name: "Measured results" }),
    ).toBeInTheDocument();
    view.changeConversation("chat2");
    expect(
      screen.queryByRole("heading", { name: "Measured results" }),
    ).not.toBeInTheDocument();
    expect(screen.queryByRole("complementary")).not.toBeInTheDocument();
  });
  it("does not let a delayed file overwrite the current preview", async () => {
    let resolveFirst!: (value: any) => void;
    vi.mocked(conversationFiles).mockResolvedValue({
      items: [file, { ...file, id: "file2", name: "metrics.csv" }],
      next_cursor: null,
    });
    vi.mocked(previewWorkbenchFile)
      .mockImplementationOnce(
        () =>
          new Promise((resolve) => {
            resolveFirst = resolve;
          }),
      )
      .mockResolvedValue({
        file_id: "file2",
        name: "metrics.csv",
        size: 10,
        revision: "1",
        kind: "table",
        rows: [
          ["metric", "value"],
          ["auc", "0.9"],
        ],
        truncated: false,
      });
    mount();
    fireEvent.click(screen.getByRole("button", { name: "Conversation files" }));
    fireEvent.click(await screen.findByRole("button", { name: "findings.md" }));
    await waitFor(() => expect(previewWorkbenchFile).toHaveBeenCalledOnce());
    const signal = vi.mocked(previewWorkbenchFile).mock.calls[0][2]!;
    fireEvent.click(screen.getByRole("button", { name: "metrics.csv" }));
    expect(await screen.findByText("0.9")).toBeInTheDocument();
    expect(signal.aborted).toBe(true);
    await act(async () =>
      resolveFirst({
        file_id: file.id,
        name: file.name,
        kind: "text",
        content: "Late old preview",
      }),
    );
    expect(screen.queryByText("Late old preview")).not.toBeInTheDocument();
  });
  it("keeps HTML previews inert and strips executable content", () => {
    const html = safePreviewHtml(
      '<script>alert(1)</script><form action="https://example.test"><input /></form><p onclick="alert(1)">Measured</p><iframe src="https://example.test"></iframe>',
    );
    expect(html).not.toContain("<script");
    expect(html).not.toContain("onclick");
    expect(html).not.toContain("<iframe");
    expect(html).toContain("default-src 'none'");
    expect(html).toContain("Measured");
  });
});
