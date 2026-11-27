import { useCallback, useEffect, useRef, useState } from "react";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { API_BASE } from "../../config";
import { apiFetch } from "../../api/client";
import {
  continueResearch,
  sendResearchMessage,
} from "../../api/autoresearch";
import {
  linkedResearch,
  referencePayload,
  resolveResources,
  type ResourceItem,
  type ResourceReference,
  type WorkbenchCommand,
} from "../../api/workbench";
import type {
  AdvancedResearchSettings,
  AutoResearchSessionSummary,
  ResearchEffort,
} from "../../types/autoresearch";
import type { WorkspaceSelection } from "../../lib/workspaceSelection";
import { PRIMARY_COMMANDS } from "./WorkbenchPicker";

export function useChatWorkbench(
  conversationId: string | null,
  userId: string | undefined,
  workspace: WorkspaceSelection,
  historyIds: string[],
) {
  const client = useQueryClient();
  const [command, setCommand] = useState<WorkbenchCommand>();
  const [references, setReferences] = useState<ResourceItem[]>([]);
  const [selected, setSelected] = useState<{
    conversation: string;
    id: string;
  }>();
  const [discuss, setDiscuss] = useState(false);
  const [planning, setPlanning] = useState(false);
  const [effort, setEffort] = useState<ResearchEffort>("medium");
  const [advanced, setAdvanced] = useState<AdvancedResearchSettings>({});
  const [downloads, setDownloads] = useState(true);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const [importing, setImporting] = useState(false);
  const sendLock = useRef(false);
  const epoch = useRef(0);
  const activeConversation = useRef(conversationId);
  activeConversation.current = conversationId;
  const links = useQuery({
    queryKey: ["chat-research-links", userId, conversationId],
    queryFn: ({ signal }) => linkedResearch(conversationId!, signal),
    enabled: !!conversationId && !!userId,
    staleTime: 5000,
  });
  const historyKey = historyIds.slice(0, 100).sort().join(",");
  const statuses = useQuery({
    queryKey: ["chat-research-status", userId, historyKey],
    queryFn: ({ signal }) =>
      apiFetch<{
        states: Record<string, string>;
        file_conversations: string[];
      }>(`${API_BASE}/workbench/research-statuses`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          conversation_ids: historyKey.split(",").filter(Boolean),
        }),
        signal,
      }),
    enabled: !!userId && !!historyKey,
    staleTime: 4000,
    refetchInterval: 8000,
    refetchIntervalInBackground: false,
  });
  const sessions = links.data?.items || [];
  const session =
    sessions.find(
      (s) =>
        selected?.conversation === conversationId &&
        selected.id === s.session_id,
    ) || sessions[0];
  useEffect(() => {
    epoch.current++;
    setCommand(undefined);
    setReferences([]);
    setDiscuss(false);
    setPlanning(false);
    setError("");
    if (conversationId)
      sessionStorage.setItem("workbench:active-conversation", conversationId);
  }, [conversationId, workspace.workspaceId, userId]);
  const addReference = useCallback((item: ResourceItem) => {
    setReferences((previous) =>
      previous.some((r) => r.id === item.id && r.kind === item.kind)
        ? previous
        : [...previous, item].slice(0, 16),
    );
  }, []);
  useEffect(() => {
    if (command?.mode === 'research') setPlanning(true);
    else if (command) setPlanning(false);
  }, [command]);
  const reset = useCallback(() => {
    epoch.current++;
    setCommand(undefined);
    setReferences([]);
    setDiscuss(false);
    setPlanning(false);
    setError("");
    setSelected(undefined);
    setAdvanced({});
    setEffort("medium");
    setDownloads(true);
  }, []);
  const started = useCallback(
    (value: AutoResearchSessionSummary) => {
      const cid = value.chat_conversation_id || activeConversation.current;
      if (!cid) return;
      setPlanning(false);
      client.setQueryData<{ items: AutoResearchSessionSummary[] }>(
        ["chat-research-links", userId, cid],
        (old) => ({
          items: [
            value,
            ...(old?.items || []).filter(
              (item) => item.session_id !== value.session_id,
            ),
          ],
        }),
      );
      setSelected({ conversation: cid, id: value.session_id });
      void client.invalidateQueries({
        queryKey: ["chat-research-status", userId],
      });
    },
    [client, userId],
  );
  const onStatus = useCallback(
    (value: AutoResearchSessionSummary) => {
      const cid = value.chat_conversation_id || activeConversation.current;
      client.setQueryData<{ items: AutoResearchSessionSummary[] }>(
        ["chat-research-links", userId, cid],
        (old) =>
          old
            ? {
                items: old.items.map((item) =>
                  item.session_id === value.session_id &&
                  item.status !== value.status
                    ? { ...item, status: value.status }
                    : item,
                ),
              }
            : old,
      );
    },
    [client, userId],
  );
  useEffect(() => {
    const handle = (event: Event) => {
      const detail = (
        event as CustomEvent<{
          goal?: string;
          datasetIds?: string[];
          conversationId?: string;
        }>
      ).detail;
      if (
        detail.conversationId &&
        detail.conversationId !== activeConversation.current
      )
        return;
      setCommand(PRIMARY_COMMANDS[0]);
      setDiscuss(false);
      if (detail.datasetIds?.length)
        resolveResources(
          detail.datasetIds.map((id) => ({ kind: "dataset", id })),
          workspace.workspaceId,
        )
          .then((value) => setReferences(value.items))
          .catch((e) => setError(e.message));
    };
    window.addEventListener("workbench:select-research", handle);
    return () =>
      window.removeEventListener("workbench:select-research", handle);
  }, [workspace.workspaceId]);

  async function sendResearch(
    text: string,
    cid: string,
    selectedCommand = command,
    refs = references,
  ) {
    if (sendLock.current || importing) return false;
    sendLock.current = true;
    setBusy(true);
    setError("");
    const currentEpoch = epoch.current;
    try {
      if (workspace.executionMode === "read_only")
        throw new Error("This workspace is read-only");
      if (session && !selectedCommand) {
        if (
          ["completed", "failed", "interrupted", "blocked", "paused"].includes(
            session.status,
          )
        ) {
          await continueResearch(session.session_id, {
            text,
            references: referencePayload(refs),
          });
        } else
          await sendResearchMessage(
            session.session_id,
            text,
            referencePayload(refs),
          );
        await client.invalidateQueries({
          queryKey: ["workbench-research", userId, session.session_id],
        });
      } else return false;
      if (currentEpoch === epoch.current) {
        setReferences([]);
        setCommand(undefined);
        setDiscuss(false);
      }
      void client.invalidateQueries({
        queryKey: ["chat-research-links", userId, cid],
      });
      return true;
    } catch (e) {
      if (currentEpoch === epoch.current) setError((e as Error).message);
      return false;
    } finally {
      setBusy(false);
      sendLock.current = false;
    }
  }
  return {
    command,
    setCommand,
    references,
    setReferences,
    addReference,
    sessions,
    session,
    setSelected,
    discuss,
    setDiscuss,
    setPlanning,
    effort,
    setEffort,
    advanced,
    setAdvanced,
    downloads,
    setDownloads,
    busy,
    error,
    setError,
    importing,
    setImporting,
    sendResearch,
    started,
    onStatus,
    reset,
    statuses: statuses.data?.states || {},
    fileConversations: statuses.data?.file_conversations || [],
    useResearch:
      command?.mode === "research" ||
      (!!session && !discuss && !planning && !command),
    chatOptions: {
      references: referencePayload(references),
      allowResearch: command?.mode !== "chat" && (!discuss || planning),
      librarySkillId: command?.library_skill_id,
      onResearchStarted: started,
      onResearchError: setError,
    },
  };
}
