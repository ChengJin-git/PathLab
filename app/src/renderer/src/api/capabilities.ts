import { API_BASE } from "../config";
import { apiFetch, downloadApiFile } from "./client";
import type { Page } from "./workbench";

export type CapabilityKind = "skill" | "connector";
export interface CapabilityEntry {
  github_source?: { url: string; path?: string; ref?: string; commit?: string; synced_at?: string; license?: string } | null;
  can_sync?: boolean;
  logo?: { source: string; license: string; kind: string } | null;
  logo_revision?: string | null;
  id: string;
  kind: CapabilityKind;
  name: string;
  description: string;
  owner_id: string | null;
  builtin: boolean;
  visibility: "private" | "public";
  revision: number;
  installed: boolean;
  enabled: boolean;
  editable: boolean;
  connected: boolean;
  has_credential: boolean;
  tool_count: number;
  content?: string;
  config?: { url?: string; transport?: string; entrypoint?: string };
  tools?: { name: string; description: string }[];
}
export interface CapabilityDraft {
  kind: CapabilityKind;
  name: string;
  description: string;
  visibility: "private" | "public";
  content: string;
  url: string;
  revision?: number;
  source_url?: string;
}
const root = () => `${API_BASE}/capabilities`;
export const syncCapability = (id: string, revision: number, source_url?: string) => apiFetch<CapabilityEntry>(`${root()}/${encodeURIComponent(id)}/sync-github`, { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ revision, source_url }) });
export const listCapabilities = (
  params: Record<string, string>,
  signal?: AbortSignal,
) =>
  apiFetch<Page<CapabilityEntry>>(`${root()}?${new URLSearchParams(params)}`, {
    signal,
  });
export const readCapability = (
  id: string,
  language: string,
  signal?: AbortSignal,
) =>
  apiFetch<CapabilityEntry>(
    `${root()}/${encodeURIComponent(id)}?language=${language}`,
    { signal },
  );
export const saveCapability = (draft: CapabilityDraft, id?: string) =>
  apiFetch<CapabilityEntry>(id ? `${root()}/${encodeURIComponent(id)}` : root(), {
    method: id ? "PUT" : "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(draft),
  });
export const installCapability = (
  id: string,
  enabled: boolean,
  token?: string,
) =>
  apiFetch<CapabilityEntry>(`${root()}/${encodeURIComponent(id)}/installation`, {
    method: "PUT",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({
      enabled,
      ...(token !== undefined ? { token } : {}),
    }),
  });
export const removeCapability = (id: string, uninstall = false) =>
  apiFetch(
    `${root()}/${encodeURIComponent(id)}${uninstall ? "/installation" : ""}`,
    { method: "DELETE" },
  );
export const connectCapability = (id: string) =>
  apiFetch<{ connected: boolean; tool_count: number }>(
    `${root()}/${encodeURIComponent(id)}/connect`,
    { method: "POST" },
  );
export function importCapability(file: File, visibility: string) {
  const body = new FormData();
  body.append("file", file);
  return apiFetch<CapabilityEntry>(
    `${root()}/import-skill?visibility=${visibility}`,
    { method: "POST", body },
  );
}

export interface SkillFile {
  path: string;
  size: number;
  executable: boolean;
}
export interface SkillFilePage extends Page<SkillFile> {
  revision: number;
  entrypoint: string;
}
export interface SkillFileContent extends SkillFile {
  revision: number;
  text: string | null;
}
const skillURL = (id: string) => `${root()}/${encodeURIComponent(id)}`;
export const listSkillFiles = (
  id: string,
  params: Record<string, string>,
  signal?: AbortSignal,
) =>
  apiFetch<SkillFilePage>(
    `${skillURL(id)}/files?${new URLSearchParams(params)}`,
    { signal },
  );
export const readSkillFile = (id: string, path: string, signal?: AbortSignal) =>
  apiFetch<SkillFileContent>(
    `${skillURL(id)}/file?${new URLSearchParams({ path })}`,
    { signal },
  );
export const saveSkillFile = (
  id: string,
  body: {
    revision: number;
    path: string;
    content: string;
    executable: boolean;
    overwrite: boolean;
  },
) =>
  apiFetch<{ revision: number }>(`${skillURL(id)}/file`, {
    method: "PUT",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  });
export const deleteSkillFile = (id: string, path: string, revision: number) =>
  apiFetch<{ revision: number }>(
    `${skillURL(id)}/file?${new URLSearchParams({ path, revision: String(revision) })}`,
    { method: "DELETE" },
  );
export function uploadSkillFile(
  id: string,
  file: File,
  path: string,
  revision: number,
  overwrite: boolean,
  executable: boolean,
) {
  const body = new FormData();
  body.append("file", file);
  return apiFetch<{ revision: number }>(
    `${skillURL(id)}/file?${new URLSearchParams({ path, revision: String(revision), overwrite: String(overwrite), executable: String(executable) })}`,
    { method: "POST", body },
  );
}
export function replaceSkillPackage(id: string, file: File, revision: number) {
  const body = new FormData();
  body.append("file", file);
  return apiFetch<{ revision: number }>(
    `${skillURL(id)}/package?revision=${revision}`,
    { method: "PUT", body },
  );
}
export const downloadSkillFile = (id: string, path: string) =>
  downloadApiFile(
    `${skillURL(id)}/file?${new URLSearchParams({ path, download: "true" })}`,
    path.split("/").pop()!,
  );
