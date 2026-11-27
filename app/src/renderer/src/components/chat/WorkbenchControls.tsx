import { useId, useRef } from "react";
import { useQuery } from '@tanstack/react-query';
import { FilePlus2, MessageCircleQuestion, X } from "lucide-react";
import { uploadWorkbenchFile } from "../../api/workbench";
import ResearchAdvancedSettings from "../autoresearch/ResearchAdvancedSettings";
import { useWorkbenchText } from "./workbenchText";
import type { useChatWorkbench } from "./useChatWorkbench";
import { FileReferenceButton, useConversationFiles } from "./ConversationFiles";
import { Select } from '../ui/select';
import { Checkbox } from '../ui/checkbox';
import { getResearchConfiguration } from '../../api/autoresearch';
import { commandLanguage, localizePrimaryCommand } from '../../locales/commands';
import { useTranslation } from 'react-i18next';

export default function WorkbenchControls({
  workbench: w,
  workspaceId,
  conversationId,
  ensureConversation,
}: {
  workbench: ReturnType<typeof useChatWorkbench>;
  workspaceId?: string | null;
  conversationId?: string | null;
  ensureConversation?: () => Promise<string>;
}) {
  const text = useWorkbenchText();
  const { i18n } = useTranslation();
  const downloadId = useId();
  const configuration = useQuery({
    queryKey: ['research-configuration'], queryFn: getResearchConfiguration,
    enabled: w.command?.mode === 'research', staleTime: 60000,
  });
  const upload = useRef<HTMLInputElement>(null);
  const files = useConversationFiles();
  return (
    <div className="px-4 pt-2 text-xs text-gray-500">
      <div className="flex flex-wrap items-center gap-2">
        <button
          type="button"
          onClick={() => upload.current?.click()}
          disabled={w.busy || w.importing || w.references.length >= 16}
          aria-label={text("upload")}
          className="rounded p-1 hover:bg-gray-100"
        >
          <FilePlus2 size={14} />
        </button>
        <input
          ref={upload}
          type="file"
          className="hidden"
          onChange={async (e) => {
            const file = e.target.files?.[0];
            e.target.value = "";
            if (!file) return;
            w.setImporting(true);
            try {
              const cid = conversationId || await ensureConversation?.();
              w.addReference(
                await uploadWorkbenchFile(file, workspaceId, cid),
              );
              files?.changed();
            } catch (error) {
              w.setError((error as Error).message);
            } finally {
              w.setImporting(false);
            }
          }}
        />
        {w.command && (
          <span className="inline-flex items-center gap-1 rounded-md bg-gray-100 px-2 py-1 text-gray-800">
            {w.command.library_skill_id ? w.command.name : localizePrimaryCommand(w.command, commandLanguage(i18n.language)).name}
            <button
              type="button"
              onClick={() => w.setCommand(undefined)}
              aria-label={text("remove")}
            >
              <X size={12} />
            </button>
          </span>
        )}
        {!w.command && w.session && (
          <Select
            ariaLabel={text("research")}
            value={w.discuss ? "discuss" : "instruct"}
            onChange={(value) => w.setDiscuss(value === "discuss")}
            className="w-40" triggerClassName="min-h-9 py-1 text-xs"
            options={[{value:'instruct',label:text('instruct')},{value:'discuss',label:text('discuss')}]}
          />
        )}
        {w.session && <button type="button" className="inline-flex items-center gap-1 rounded-md border px-2 py-1.5 text-primary-700 hover:bg-primary-50"
          title={text('sideQuestionHint')} onClick={()=>window.dispatchEvent(new CustomEvent('workbench:research-question',{detail:{sessionId:w.session!.session_id}}))}>
          <MessageCircleQuestion size={14}/>{text('sideQuestion')}
        </button>}
        {!w.command && !w.session && (
          <span className="text-gray-400">{text("hint")}</span>
        )}
      </div>
      {w.references.length > 0 && (
        <div className="mt-2 flex flex-wrap gap-1.5">
          {w.references.map((item) => (
            <span
              key={`${item.kind}:${item.id}`}
              title={item.name}
              className="inline-flex max-w-60 items-center gap-1 rounded-md border px-2 py-1"
            >
              <FileReferenceButton file={item} />
              <button
                type="button"
                aria-label={`${text("remove")} ${item.name}`}
                onClick={() =>
                  w.setReferences((items) =>
                    items.filter(
                      (r) => r.id !== item.id || r.kind !== item.kind,
                    ),
                  )
                }
              >
                <X size={12} />
              </button>
            </span>
          ))}
        </div>
      )}
      {w.command?.mode === "research" && (
        <div className="mt-3 space-y-2 border-t pt-2">
          <p className="text-xs leading-5 text-slate-600">{text('briefHint')}</p>
          <div className="flex flex-wrap items-center gap-3">
            <div className="flex items-center gap-2">
              <span>{text("effort")}</span>
              <Select ariaLabel={text('effort')}
                value={w.effort}
                onChange={(value) => {
                  w.setEffort(value as "low" | "medium" | "high");
                  w.setAdvanced((previous) => ({ skills: previous.skills }));
                }}
                className="w-24" triggerClassName="min-h-9 py-1 text-xs"
                disabled={w.busy || w.importing}
                options={(['low','medium','high'] as const).map(value=>({value,label:text(value)}))}
              />
            </div>
            <div className="flex min-h-9 items-center gap-2">
              <Checkbox id={downloadId}
                checked={w.downloads}
                onCheckedChange={w.setDownloads}
                disabled={w.busy || w.importing}
              />
              <label htmlFor={downloadId} className="cursor-pointer">{text("downloads")}</label>
            </div>
          </div>
          <ResearchAdvancedSettings
            value={w.advanced}
            defaults={configuration.data?.effort_presets.standard[w.effort]}
            onChange={w.setAdvanced}
            disabled={w.busy}
            onImportingChange={w.setImporting}
          />
        </div>
      )}
      {w.error && (
        <p role="alert" className="mt-2 text-red-600">
          {w.error}
        </p>
      )}
    </div>
  );
}
