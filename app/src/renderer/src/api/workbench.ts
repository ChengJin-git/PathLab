import { API_BASE } from "../config";
import { apiFetch, apiFetchBlob, downloadApiFile } from "./client";
import type {
  AutoResearchEvent,
  AutoResearchSessionSummary,
} from "../types/autoresearch";

export type ResourceKind =
   "dataset" | "slide" | "task" | "model" | "file" | "research" | "conversation";
export interface ResourceReference {
  kind: ResourceKind;
  id: string;
  revision?: string;
}
export interface ResourceItem extends ResourceReference {
  name: string;
  entry_kind?: string;
  path?: string;
  session_id?: string;
  size?: number;
  source_title?: string | null;
}
export interface WorkbenchCommand {
  id: string;
  name: string;
  description: string;
  skill_id?: string;
  mode: "chat" | "research" | "skill";
  library_skill_id?: string;
  available?: boolean;
}
export interface Page<T> {
  items: T[];
  next_cursor: string | null;
}
export const referencePayload = (
  items: ResourceReference[],
): ResourceReference[] =>
  items.map(({ kind, id, revision }) => ({ kind, id, revision }));

export function searchResources(
  params: Record<string, string>,
  signal?: AbortSignal,
): Promise<Page<ResourceItem>> {
  return apiFetch(
    `${API_BASE}/workbench/resources?${new URLSearchParams(params)}`,
    { signal },
  );
}
export function searchCommands(
  q = "",
  after = "",
  signal?: AbortSignal,
  language = "en-US",
): Promise<Page<WorkbenchCommand>> {
  return apiFetch(
    `${API_BASE}/workbench/commands?${new URLSearchParams({ q, after, language })}`,
    { signal },
  );
}
export function resolveResources(
  items: ResourceReference[],
  workspaceId?: string | null,
): Promise<{ items: ResourceItem[] }> {
  return apiFetch(`${API_BASE}/workbench/resolve`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({
      workspace_id: workspaceId,
      references: referencePayload(items),
    }),
  });
}
export function uploadWorkbenchFile(
  file: File,
  workspaceId?: string | null,
  conversationId?: string | null,
): Promise<ResourceItem> {
  const form = new FormData();
  form.append("file", file);
  const params = new URLSearchParams();
  if (workspaceId) params.set("workspace_id", workspaceId);
  if (conversationId) params.set("conversation_id", conversationId);
  return apiFetch(`${API_BASE}/workbench/uploads?${params}`, {
    method: "POST",
    body: form,
  });
}
export function linkedResearch(
  id: string,
  signal?: AbortSignal,
): Promise<{ items: AutoResearchSessionSummary[] }> {
  return apiFetch(
    `${API_BASE}/workbench/conversations/${encodeURIComponent(id)}/research`,
    { signal },
  );
}
export function researchActivity(
  id: string,
  before = 0,
): Promise<{ items: AutoResearchEvent[]; next_before: number | null }> {
  return apiFetch(
    `${API_BASE}/workbench/research/${encodeURIComponent(id)}/activity?before=${before}`,
  );
}

export interface ResearchQuestionTurn { role: 'user' | 'assistant'; content: string }
export function askResearchQuestion(id: string, body: {
  question: string; event_seq?: number; history: ResearchQuestionTurn[]; language: string;
}, signal?: AbortSignal): Promise<{answer: string; research_unchanged: boolean}> {
  return apiFetch(`${API_BASE}/workbench/research/${encodeURIComponent(id)}/questions`, {
    method: 'POST', headers: {'Content-Type': 'application/json'}, body: JSON.stringify(body), signal,
  });
}
export function indexResearchFiles(
  id: string,
  path = "",
): Promise<{ status: string }> {
  return apiFetch(
    `${API_BASE}/workbench/research/${encodeURIComponent(id)}/index?path=${encodeURIComponent(path)}`,
    { method: "POST" },
  );
}
export function previewWorkbenchFile(
  id: string,
  workspaceId?: string | null,
  signal?: AbortSignal,
  sheet = "",
): Promise<FilePreview> {
  const params = new URLSearchParams({ sheet });
  if (workspaceId) params.set("workspace_id", workspaceId);
  return apiFetch(
    `${API_BASE}/workbench/files/${encodeURIComponent(id)}?${params}`,
    { signal },
  );
}
export interface FilePreview {
  file_id: string;
  name: string;
  size: number;
  revision: string;
  kind:
    | "image"
    | "audio"
    | "video"
    | "pdf"
    | "markdown"
    | "text"
    | "code"
    | "html"
    | "table"
    | "document"
    | "slides"
    | "unsupported";
  content?: string;
  page_count?: number;
  page_width?: number;
  page_height?: number;
  first_page?: string | null;
  rows?: string[][];
  sheets?: string[];
  sheet?: string;
  truncated: boolean;
  reason?: "previewTooLarge" | "previewUnavailable" | "unsupportedPreview" | "previewTimeout" | "previewRendererUnavailable" | "previewBusy";
}
export function readWorkbenchPage(id: string, page: number, revision: string, workspaceId?: string | null, signal?: AbortSignal): Promise<Blob> {
  const params = new URLSearchParams({ revision });
  if (workspaceId) params.set("workspace_id", workspaceId);
  return apiFetchBlob(`${API_BASE}/workbench/files/${encodeURIComponent(id)}/pages/${page}?${params}`, { signal });
}
function fileContentUrl(
  id: string,
  workspaceId?: string | null,
  download = false,
) {
  const params = new URLSearchParams({ download: String(download) });
  if (workspaceId) params.set("workspace_id", workspaceId);
  return `${API_BASE}/workbench/files/${encodeURIComponent(id)}/content?${params}`;
}
export function readWorkbenchMedia(
  id: string,
  workspaceId?: string | null,
  signal?: AbortSignal,
): Promise<Blob> {
  return apiFetchBlob(fileContentUrl(id, workspaceId), { signal });
}
export function downloadWorkbenchFile(
  item: ResourceItem,
  workspaceId?: string | null,
) {
  return downloadApiFile(fileContentUrl(item.id, workspaceId, true), item.name);
}
export function downloadConversationFile(
  conversationId: string,
  file: ResourceItem,
) {
  return downloadApiFile(
    `${API_BASE}/workbench/conversations/${encodeURIComponent(conversationId)}/files/${encodeURIComponent(file.id)}/download`,
    file.name,
  );
}
export function conversationFiles(
  conversationId: string,
  params: Record<string, string>,
  signal?: AbortSignal,
): Promise<Page<ResourceItem> & { indexing?: boolean; partial?: boolean }> {
  return apiFetch(
    `${API_BASE}/workbench/conversations/${encodeURIComponent(conversationId)}/files?${new URLSearchParams(params)}`,
    { signal },
  );
}
export function referenceResearchPath(
  id: string,
  path: string,
  signal?: AbortSignal,
  includePreview = false,
): Promise<ResourceItem & {preview?: FilePreview}> {
  return apiFetch(
    `${API_BASE}/workbench/research/${encodeURIComponent(id)}/file-reference`,
    {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ path, include_preview: includePreview }),
      signal,
    },
  );
}
