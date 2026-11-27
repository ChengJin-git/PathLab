import { API_BASE } from "../config";
import { apiFetch } from "./client";
import type { Conversation } from "./chat";
import type { Page } from "./workbench";
export interface ChatFolder {
  id: string;
  name: string;
}
export type FiledChat = Conversation & {
  folder_id: string | null;
  folder_name: string | null;
  pinned: boolean;
};
const root = () => `${API_BASE}/chat-navigation`;
export const listChatFolders = (after = "", signal?: AbortSignal) =>
  apiFetch<Page<ChatFolder>>(
    `${root()}/folders?${new URLSearchParams({ after, limit: "50" })}`,
    { signal },
  );
export const saveChatFolder = (name: string, id?: string) =>
  apiFetch<ChatFolder>(
    `${root()}/folders${id ? "/" + encodeURIComponent(id) : ""}`,
    {
      method: id ? "PATCH" : "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ name }),
    },
  );
export const deleteChatFolder = (id: string) =>
  apiFetch(`${root()}/folders/${encodeURIComponent(id)}`, { method: "DELETE" });
export const fileChat = (
  id: string,
  body: { folder_id?: string | null; pinned?: boolean; title?: string },
) =>
  apiFetch(`${root()}/chats/${encodeURIComponent(id)}`, {
    method: "PATCH",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  });
export const listFiledChats = (
  folder = "",
  q = "",
  cursor = "",
  signal?: AbortSignal,
) =>
  apiFetch<Page<FiledChat>>(
    `${root()}/chats?${new URLSearchParams({ folder, q, cursor })}`,
    { signal },
  );
export const chatNavigationChanged = () =>
  window.dispatchEvent(new Event("chat-navigation:changed"));
