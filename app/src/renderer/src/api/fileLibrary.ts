import { API_BASE } from "../config";
import { apiFetch } from "./client";
import type { Page, ResourceItem } from "./workbench";
export interface LibraryFile extends ResourceItem {
  kind: "file";
  revision: string;
  folder_id: string | null;
  origin: "upload" | "generated";
  owner_id: string;
  owner_name?: string;
  conversation_id: string | null;
  source_title: string | null;
  updated_at: string;
  index_status: string;
  index_progress: number;
  index_error: string | null;
  editable_text?: boolean;
}
export interface LibraryGroup {
  id: string;
  title: string | null;
  file_count: number;
  total_size: number;
  updated_at: string;
}
export const libraryGroups = (
  params: Record<string, string>,
  signal?: AbortSignal,
) =>
  apiFetch<Page<LibraryGroup>>(
    `${root()}/groups?${new URLSearchParams(params)}`,
    { signal },
  );
export const batchLibraryFiles = (
  files: { id: string; revision: string; updated_at: string; name?: string }[],
  operation: "edit" | "delete",
  folder_id?: string | null,
) =>
  apiFetch(`${root()}/batch`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({
      files,
      operation,
      ...(folder_id !== undefined ? { folder_id } : {}),
    }),
  });
export const readLibraryText = (id: string) =>
  apiFetch<{ content: string; revision: string }>(`${root()}/files/${id}/text`);
export const saveLibraryText = (
  id: string,
  revision: string,
  content: string,
) =>
  apiFetch<LibraryFile>(`${root()}/files/${id}/text`, {
    method: "PUT",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ revision, content }),
  });
export interface LibraryFolder {
  id: string;
  name: string;
  owner_id: string;
}
export interface FileHit {
  file_id: string;
  revision: string;
  name: string;
  page: number;
  section: string;
  text: string;
  score: number;
  url: string;
}
const root = () => API_BASE + "/file-library";
export const libraryFiles = (
  params: Record<string, string>,
  signal?: AbortSignal,
) =>
  apiFetch<Page<LibraryFile>>(`${root()}?${new URLSearchParams(params)}`, {
    signal,
  });
export const libraryFile = (id: string, signal?: AbortSignal) =>
  apiFetch<LibraryFile>(`${root()}/files/${id}`, { signal });
export const libraryFolders = (view: string, signal?: AbortSignal) =>
  apiFetch<{ items: LibraryFolder[] }>(`${root()}/folders?view=${view}`, {
    signal,
  });
export const libraryOwners = (signal?: AbortSignal) =>
  apiFetch<{ items: { id: string; name: string }[] }>(`${root()}/owners`, {
    signal,
  });
export const saveLibraryFolder = (name: string, id?: string) =>
  apiFetch<LibraryFolder>(`${root()}/folders${id ? "/" + id : ""}`, {
    method: id ? "PATCH" : "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ name }),
  });
export const deleteLibraryFolder = (id: string) =>
  apiFetch(`${root()}/folders/${id}`, { method: "DELETE" });
export const editLibraryFile = (
  file: LibraryFile,
  body: { name?: string; folder_id?: string | null },
) =>
  apiFetch<LibraryFile>(`${root()}/files/${file.id}`, {
    method: "PATCH",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({
      ...body,
      revision: file.revision,
      updated_at: file.updated_at,
    }),
  });
export const deleteLibraryFile = (id: string) =>
  apiFetch(`${root()}/files/${id}`, { method: "DELETE" });
export function uploadLibraryFile(file: File, existing?: LibraryFile) {
  const body = new FormData();
  body.append("file", file);
  return apiFetch<LibraryFile>(
    existing
      ? `${root()}/files/${existing.id}/content?revision=${existing.revision}`
      : `${root()}/upload`,
    { method: existing ? "PUT" : "POST", body },
  );
}
export const indexLibraryFile = (id: string, cancel = false) =>
  apiFetch(`${root()}/files/${id}/index`, {
    method: cancel ? "DELETE" : "POST",
  });
export const searchLibrary = (
  query: string,
  options: {
    file_ids?: string[];
    folder?: string;
    all_users?: boolean;
    owner?: string;
  } = {},
  signal?: AbortSignal,
) =>
  apiFetch<{ items: FileHit[] }>(`${root()}/search`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ query, ...options }),
    signal,
  });
