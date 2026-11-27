import {
  cleanup,
  fireEvent,
  render,
  screen,
  waitFor,
  within,
  act,
} from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { MemoryRouter, useLocation } from "react-router-dom";
import { afterEach, beforeEach, expect, it, vi } from "vitest";
import WorkbenchSidebar from "@renderer/components/chat/WorkbenchSidebar";
import * as api from "@renderer/api/chatNavigation";
import { deleteConversation } from '@renderer/api/chat';
import userEvent from '@testing-library/user-event';
import i18n from "@renderer/i18n";
vi.mock("@renderer/contexts/AuthContext", () => ({
  useAuth: () => ({ user: { id: "a" } }),
}));
vi.mock("@renderer/components/BackgroundTaskPanel", () => ({
  BackgroundTaskPanel: () => <button>Background progress</button>,
}));
vi.mock("@renderer/components/chat/HistoryFiles", () => ({
  default: () => null,
}));
vi.mock("@renderer/api/chatNavigation", () => ({
  listChatFolders: vi.fn(),
  listFiledChats: vi.fn(),
  saveChatFolder: vi.fn(),
  deleteChatFolder: vi.fn(),
  fileChat: vi.fn(),
  chatNavigationChanged: vi.fn(),
}));
vi.mock("@renderer/api/chat", () => ({
  createConversation: vi.fn(),
  deleteConversation: vi.fn(),
  getConversation: vi.fn(),
}));
vi.mock("@renderer/api/client", () => ({
  apiFetch: vi.fn().mockResolvedValue({ states: {}, file_conversations: [] }),
  downloadBlobFile: vi.fn(),
}));
beforeEach(async () => {
  await i18n.changeLanguage("en-US");
  localStorage.clear();
  vi.mocked(api.listChatFolders).mockResolvedValue({
    items: [{ id: "f", name: "My study" }],
    next_cursor: null,
  });
  vi.mocked(api.listFiledChats).mockResolvedValue({
    items: [
      {
        conversation_id: "c",
        user_id: "a",
        workspace_id: null,
        title: "My chat",
        folder_id: null,
        folder_name: null,
        pinned: false,
        created_at: "2026-01-01",
        updated_at: "2026-01-01",
      },
    ],
    next_cursor: null,
  });
});
afterEach(() => {
  cleanup();
  vi.clearAllMocks();
});
function show(cache = new QueryClient({defaultOptions: {queries: {retry: false}}})) {
  function Location(){return <output data-testid="location">{useLocation().pathname}</output>}
  return render(
    <MemoryRouter initialEntries={["/dashboard/c"]}>
      <QueryClientProvider
        client={cache}
      >
        <WorkbenchSidebar />
        <Location />
      </QueryClientProvider>
    </MemoryRouter>,
  );
}
it('restores direct manual upload navigation with active sidebar styling', async()=>{
  show()
  fireEvent.click(screen.getByRole('button',{name:'Upload data'}))
  expect(screen.getByTestId('location')).toHaveTextContent('/upload')
  expect(screen.getByRole('button',{name:'Upload data'})).toHaveAttribute('aria-current','page')
})
it("supports desktop dropping a chat into a folder without changing chat scope", async () => {
  show();
  const chat = await screen.findByRole("button", { name: "My chat" });
  const folder = screen.getByRole("region", { name: "My study" });
  const data = {
    getData: () => "c",
    setData: vi.fn(),
    types: ["application/pathlab-chat"],
    effectAllowed: "",
  };
  fireEvent.dragStart(chat.closest("[draggable]")!, { dataTransfer: data });
  expect(data.setData).toHaveBeenCalledWith("application/pathlab-chat", "c");
  fireEvent.drop(folder, { dataTransfer: data });
  await waitFor(() =>
    expect(api.fileChat).toHaveBeenCalledWith("c", { folder_id: "f" }),
  );
});
it("stores folder expansion by account and keeps background progress when collapsed", async () => {
  show();
  fireEvent.click(await screen.findByRole("button", { name: "My study" }));
  await waitFor(() =>
    expect(JSON.parse(localStorage.getItem("chat-folders:a")!)).toEqual(["f"]),
  );
  fireEvent.click(
    within(screen.getByRole("complementary")).getByRole("button", {
      name: "Close sidebar",
    }),
  );
  expect(
    screen.getByRole("button", { name: "Background progress" }),
  ).toBeInTheDocument();
  expect(
    screen.queryByRole("button", { name: "My study" }),
  ).not.toBeInTheDocument();
});

it('removes a chat and closes confirmation before the request resolves, including late list responses', async () => {
  let resolve!: () => void;
  vi.mocked(deleteConversation).mockImplementation(() => new Promise<void>(done => {resolve = done}));
  const cache = new QueryClient({defaultOptions: {queries: {retry: false}}});
  const user = userEvent.setup();
  show(cache);
  await screen.findByRole('button',{name:'My chat'});
  await user.click(screen.getByRole('button',{name:'Chat options: My chat'}));
  await user.click(screen.getByRole('menuitem',{name:'Delete chat'}));
  await user.click(within(screen.getByRole('dialog')).getByRole('button',{name:'Delete chat'}));
  expect(deleteConversation).toHaveBeenCalledWith('c');
  expect(screen.queryByRole('dialog')).not.toBeInTheDocument();
  expect(screen.queryByRole('button',{name:'My chat'})).not.toBeInTheDocument();
  expect(screen.getByTestId('location')).toHaveTextContent('/dashboard');
  await act(async () => {await cache.invalidateQueries({queryKey:['filed-chats']})});
  expect(screen.queryByRole('button',{name:'My chat'})).not.toBeInTheDocument();
  await act(async () => resolve());
  expect(screen.queryByRole('button',{name:'My chat'})).not.toBeInTheDocument();
});

it('restores a rejected deletion with a localized retry message', async () => {
  await i18n.changeLanguage('zh-CN');
  let reject!: (error: Error) => void;
  vi.mocked(deleteConversation).mockImplementation(() => new Promise<void>((_,fail) => {reject = fail}));
  const user = userEvent.setup();show();
  await screen.findByRole('button',{name:'My chat'});
  await user.click(screen.getByRole('button',{name:'聊天选项: My chat'}));
  await user.click(screen.getByRole('menuitem',{name:'删除聊天'}));
  await user.click(within(screen.getByRole('dialog')).getByRole('button',{name:'删除聊天'}));
  expect(screen.queryByRole('button',{name:'My chat'})).not.toBeInTheDocument();
  await act(async () => reject(new Error('Internal server error')));
  expect(await screen.findByRole('button',{name:'My chat'})).toBeVisible();
  expect(screen.getByRole('alert')).toHaveTextContent('未能删除此对话，已恢复到列表，请重试。');
  expect(screen.queryByText('Internal server error')).not.toBeInTheDocument();
});
