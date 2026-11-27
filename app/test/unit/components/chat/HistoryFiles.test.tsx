import {
  cleanup,
  fireEvent,
  render,
  screen,
  waitFor,
} from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { afterEach, beforeEach, expect, it, vi } from "vitest";
import HistoryFiles from "@renderer/components/chat/HistoryFiles";
import {
  conversationFiles,
  downloadConversationFile,
} from "@renderer/api/workbench";
import i18n from "@renderer/i18n";

vi.mock("@renderer/api/workbench", () => ({
  conversationFiles: vi.fn(),
  downloadConversationFile: vi.fn(),
}));
beforeEach(async () => {
  await i18n.changeLanguage("en-US");
  vi.mocked(conversationFiles).mockReset();
  vi.mocked(downloadConversationFile).mockReset();
});
afterEach(cleanup);

it("loads only the expanded conversation and pages forward and back without accumulating rows", async () => {
  const client = new QueryClient({
    defaultOptions: { queries: { retry: false } },
  });
  vi.mocked(conversationFiles).mockImplementation(async (_id, params) => ({
    items: Array.from({ length: 20 }, (_, i) => ({
      kind: "file",
      id: `${params.cursor || "first"}-${i}`,
      name: `${params.cursor ? "Next" : "First"} ${i}.md`,
    })),
    next_cursor: params.cursor ? null : "next",
  }));
  const onOpen = vi.fn();
  const view = render(
    <QueryClientProvider client={client}>
      <HistoryFiles
        conversationId="one"
        userId="owner"
        expanded={false}
        onToggle={vi.fn()}
        onOpen={onOpen}
      />
    </QueryClientProvider>,
  );
  expect(conversationFiles).not.toHaveBeenCalled();
  view.rerender(
    <QueryClientProvider client={client}>
      <HistoryFiles
        conversationId="one"
        userId="owner"
        expanded
        onToggle={vi.fn()}
        onOpen={onOpen}
      />
    </QueryClientProvider>,
  );
  expect(await screen.findByText("First 0.md")).toBeInTheDocument();
  expect(screen.getAllByRole("listitem")).toHaveLength(20);
  expect(screen.getByRole("button", { name: "Previous page" })).toBeDisabled();
  fireEvent.click(screen.getByRole("button", { name: "Next page" }));
  expect(await screen.findByText("Next 0.md")).toBeInTheDocument();
  expect(screen.queryByText("First 0.md")).not.toBeInTheDocument();
  expect(screen.getAllByRole("listitem")).toHaveLength(20);
  fireEvent.click(screen.getByRole("button", { name: "Previous page" }));
  expect(await screen.findByText("First 0.md")).toBeInTheDocument();
  fireEvent.click(screen.getByRole("button", { name: "First 0.md" }));
  expect(onOpen).toHaveBeenCalledWith(
    expect.objectContaining({ id: "first-0" }),
  );
  fireEvent.click(screen.getByRole("button", { name: "Download First 0.md" }));
  await waitFor(() =>
    expect(downloadConversationFile).toHaveBeenCalledWith(
      "one",
      expect.objectContaining({ id: "first-0" }),
    ),
  );
  expect(conversationFiles).toHaveBeenCalledWith(
    "one",
    expect.objectContaining({ view: "all" }),
    expect.any(AbortSignal),
  );
});

it("aborts the current history query on collapse", async () => {
  const client = new QueryClient({
    defaultOptions: { queries: { retry: false } },
  });
  vi.mocked(conversationFiles).mockImplementation(() => new Promise(() => {}));
  const view = render(
    <QueryClientProvider client={client}>
      <HistoryFiles
        conversationId="one"
        userId="owner"
        expanded
        onToggle={vi.fn()}
        onOpen={vi.fn()}
      />
    </QueryClientProvider>,
  );
  await waitFor(() => expect(conversationFiles).toHaveBeenCalledOnce());
  const signal = vi.mocked(conversationFiles).mock.calls[0][2]!;
  view.rerender(
    <QueryClientProvider client={client}>
      <HistoryFiles
        conversationId="one"
        userId="owner"
        expanded={false}
        onToggle={vi.fn()}
        onOpen={vi.fn()}
      />
    </QueryClientProvider>,
  );
  expect(signal.aborted).toBe(true);
});
