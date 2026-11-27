import { useEffect, useRef, useState } from "react";
import {
  ChevronDown,
  Download,
  Loader2,
  Plus,
  Trash2,
  Upload,
  FolderOpen,
} from "lucide-react";
import { Button } from "../ui/button";
import { Input } from "../ui/input";
import { Checkbox } from '../ui/checkbox';
import {
  importResearchSkill,
  uploadResearchSkills,
} from "../../api/autoresearch";
import type { ResearchCopy } from "../../locales/research";
import { useResearchText } from "./researchText";
import type {
  AdvancedResearchSettings,
  ResearchBudget,
  ResearchSkill,
  ResearchSkillImport,
} from "../../types/autoresearch";

interface Props {
  value: AdvancedResearchSettings;
  defaults?: ResearchBudget;
  onChange: (value: AdvancedResearchSettings) => void;
  disabled: boolean;
  onImportingChange: (value: boolean) => void;
}

export default function ResearchAdvancedSettings({
  value,
  defaults,
  onChange,
  disabled,
  onImportingChange,
}: Props) {
  const { text } = useResearchText();
  const [url, setUrl] = useState("");
  const [open, setOpen] = useState(false);
  const [importing, setImporting] = useState(false);
  const [error, setError] = useState("");
  const [preview, setPreview] = useState<ResearchSkillImport>();
  const [selection, setSelection] = useState<number[]>([]);
  const fileInput = useRef<HTMLInputElement>(null);
  const directoryInput = useRef<HTMLInputElement>(null);
  const request = useRef<AbortController>();
  const latest = useRef(value);
  latest.current = value;
  useEffect(() => () => request.current?.abort(), []);
  useEffect(() => {
    directoryInput.current?.setAttribute("webkitdirectory", "");
  }, []);
  const skills = value.skills || [];
  const locked = disabled || importing;
  const errorText = (code: string) =>
    text[code as keyof ResearchCopy] || text.skillImportFailed;
  const customized =
    value.max_experiments !== undefined ||
    value.time_budget_seconds !== undefined;

  function updateSkill(index: number, patch: Partial<ResearchSkill>) {
    onChange({
      ...value,
      skills: skills.map((skill, i) =>
        i === index ? { ...skill, ...patch } : skill,
      ),
    });
  }

  async function importSource(files?: File[]) {
    if (
      (!files && !url.trim()) ||
      request.current ||
      disabled ||
      skills.length >= 32
    )
      return;
    const controller = new AbortController();
    request.current = controller;
    setImporting(true);
    onImportingChange(true);
    setError("");
    try {
      if (
        files &&
        (files.length > 4096 ||
          files.reduce((sum, file) => sum + file.size, 0) > 64 * 1024 * 1024)
      ) {
        throw new Error("skillTooLarge");
      }
      const imported = files
        ? await uploadResearchSkills(files, controller.signal)
        : await importResearchSkill(url.trim(), controller.signal);
      if (controller.signal.aborted) return;
      setPreview(imported);
      setSelection(
        imported.skills
          .slice(0, 32 - (latest.current.skills?.length || 0))
          .map((_, index) => index),
      );
      setUrl("");
    } catch (e) {
      if (!controller.signal.aborted)
        setError(e instanceof Error ? e.message : "skillImportFailed");
    } finally {
      if (!controller.signal.aborted) {
        request.current = undefined;
        setImporting(false);
        onImportingChange(false);
      }
    }
  }

  return (
    <details
      open={open}
      onToggle={(e) => setOpen(e.currentTarget.open)}
      onInvalidCapture={() => setOpen(true)}
      className="group/advanced border-t border-gray-100 pt-4"
    >
      <summary className="flex min-h-10 cursor-pointer list-none items-center gap-2 text-sm font-medium text-gray-700 [&::-webkit-details-marker]:hidden">
        <ChevronDown
          size={15}
          className="transition-transform group-open/advanced:rotate-180"
        />
        {text.advancedSettings}
        {customized && (
          <span className="ml-auto text-xs font-normal text-gray-500">
            {text.customBudget}
          </span>
        )}
      </summary>
      <div className="mt-3 space-y-5">
        <div className="grid gap-4 sm:grid-cols-2">
          <label className="space-y-2 text-xs font-medium text-gray-600">
            <span>{text.maxExperiments}</span>
            <Input
              type="number"
              min={1}
              max={100}
              step={1}
              disabled={locked || !defaults}
              value={value.max_experiments ?? defaults?.max_experiments ?? ""}
              onChange={(e) =>
                onChange({
                  ...value,
                  max_experiments:
                    e.target.value === "" ? undefined : Number(e.target.value),
                })
              }
            />
          </label>
          <label className="space-y-2 text-xs font-medium text-gray-600">
            <span>{text.timeBudgetHours}</span>
            <Input
              type="number"
              min={0.1}
              max={72}
              step={0.1}
              disabled={locked || !defaults}
              value={
                (value.time_budget_seconds ?? defaults?.time_budget_seconds) ===
                undefined
                  ? ""
                  : (value.time_budget_seconds ??
                      defaults!.time_budget_seconds) / 3600
              }
              onChange={(e) =>
                onChange({
                  ...value,
                  time_budget_seconds:
                    e.target.value === ""
                      ? undefined
                      : Math.round(Number(e.target.value) * 3600),
                })
              }
            />
          </label>
        </div>
        <div className="flex flex-wrap items-center justify-between gap-2">
          <p className="text-xs leading-6 text-gray-500">{text.budgetHint}</p>
          {customized && (
            <Button
              type="button"
              size="sm"
              variant="ghost"
              disabled={locked}
              onClick={() => onChange({ skills })}
            >
              {text.resetBudget}
            </Button>
          )}
        </div>
        <div className="space-y-3 border-t border-gray-100 pt-4">
          <div className="flex flex-wrap items-center justify-between gap-2">
            <h3 className="text-sm font-medium text-gray-800">
              {text.customSkills}
            </h3>
            <Button
              type="button"
              size="sm"
              variant="outline"
              disabled={locked || skills.length >= 32}
              onClick={() =>
                onChange({
                  ...value,
                  skills: [...skills, { name: text.newSkillName, content: "" }],
                })
              }
            >
              <Plus size={14} className="mr-1" />
              {text.addSkill}
            </Button>
          </div>
          <p className="text-xs leading-6 text-gray-500">{text.skillsHint}</p>
          <div className="flex flex-wrap gap-2">
            <Button
              type="button"
              size="sm"
              variant="outline"
              disabled={locked || skills.length >= 32}
              onClick={() => fileInput.current?.click()}
            >
              <Upload size={14} className="mr-1" />
              {text.skillUpload}
            </Button>
            <Button
              type="button"
              size="sm"
              variant="outline"
              disabled={locked || skills.length >= 32}
              onClick={() => directoryInput.current?.click()}
            >
              <FolderOpen size={14} className="mr-1" />
              {text.skillFolder}
            </Button>
            <input
              ref={fileInput}
              type="file"
              accept=".zip,.skill,.md,.markdown"
              multiple
              className="hidden"
              aria-label={text.skillUpload}
              onChange={(e) => {
                if (e.target.files?.length)
                  void importSource(Array.from(e.target.files));
                e.target.value = "";
              }}
            />
            <input
              ref={directoryInput}
              type="file"
              multiple
              className="hidden"
              aria-label={text.skillFolder}
              onChange={(e) => {
                if (e.target.files?.length)
                  void importSource(Array.from(e.target.files));
                e.target.value = "";
              }}
            />
          </div>
          <div className="flex flex-col gap-2 sm:flex-row">
            <Input
              aria-label={text.skillUrl}
              type="url"
              placeholder={text.skillUrlPlaceholder}
              value={url}
              disabled={locked || skills.length >= 32}
              onChange={(e) => setUrl(e.target.value)}
              onKeyDown={(e) => {
                if (e.key === "Enter") {
                  e.preventDefault();
                  void importSource();
                }
              }}
              className="min-w-0 flex-1"
            />
            <Button
              type="button"
              size="sm"
              variant="outline"
              className="h-11 gap-2"
              onClick={() => void importSource()}
              disabled={locked || !url.trim() || skills.length >= 32}
            >
              {importing ? (
                <Loader2 size={14} className="animate-spin" />
              ) : (
                <Download size={14} />
              )}
              {importing ? text.importingSkill : text.importSkill}
            </Button>
          </div>
          {error && (
            <p role="alert" className="text-xs leading-6 text-red-700">
              {errorText(error)}
            </p>
          )}
          {preview && (
            <section className="space-y-3 rounded-xl border border-blue-200 bg-blue-50/40 p-4">
              <h4 className="text-sm font-medium">
                {text.skillPreview} · {preview.skills.length} /{" "}
                {preview.files.length} {text.files}
              </h4>
              <p className="text-xs leading-6 text-gray-600">
                {text.skillOriginalLanguage}
              </p>
              {preview.warnings.map((code) => (
                <p key={code} className="text-xs leading-6 text-amber-800">
                  {errorText(code)}
                </p>
              ))}
              <div className="max-h-64 space-y-2 overflow-auto">
                {preview.skills.map((skill, index) => (
                  <div
                    key={skill.entrypoint || index}
                    className="flex items-start gap-2 text-sm"
                  >
                    <Checkbox aria-label={skill.name}
                      checked={selection.includes(index)}
                      disabled={
                        locked ||
                        (!selection.includes(index) &&
                          selection.length + skills.length >= 32)
                      }
                      onCheckedChange={(checked) =>
                        setSelection((current) =>
                          checked
                            ? [...current, index]
                            : current.filter((i) => i !== index),
                        )
                      }
                    />
                    <span className="min-w-0 break-words">
                      {skill.name}
                      <small className="block break-all text-gray-500">
                        {skill.entrypoint}
                      </small>
                    </span>
                  </div>
                ))}
              </div>
              <details className="text-xs">
                <summary className="cursor-pointer">
                  {text.skillResources} ·{" "}
                  {(preview.total_bytes / 1024 / 1024).toFixed(1)} MiB
                </summary>
                <ul className="mt-2 max-h-48 overflow-auto font-mono">
                  {preview.files.map((file) => (
                    <li key={file.path} className="break-all">
                      {file.path} · {file.size} B
                    </li>
                  ))}
                </ul>
              </details>
              <div className="flex gap-2">
                <Button
                  type="button"
                  size="sm"
                  disabled={
                    locked ||
                    !selection.length ||
                    selection.length + skills.length > 32
                  }
                  onClick={() => {
                    const added = selection
                      .map((index) => preview.skills[index])
                      .filter(
                        (item) =>
                          !skills.some(
                            (existing) =>
                              existing.package_id === item.package_id &&
                              existing.entrypoint === item.entrypoint,
                          ),
                      );
                    onChange({ ...value, skills: [...skills, ...added] });
                    setPreview(undefined);
                  }}
                >
                  {text.skillAddSelected} ({selection.length})
                </Button>
                <Button
                  type="button"
                  size="sm"
                  variant="ghost"
                  disabled={locked}
                  onClick={() => setPreview(undefined)}
                >
                  {text.skillDiscard}
                </Button>
              </div>
            </section>
          )}
          {skills.map((skill, index) => (
            <div
              key={index}
              className="space-y-3 rounded-xl border border-gray-200 bg-gray-50/50 p-3 sm:p-4"
            >
              <div className="flex items-center gap-2">
                <Input
                  aria-label={`${text.skillName} ${index + 1}`}
                  value={skill.name}
                  maxLength={80}
                  required
                  disabled={locked}
                  onChange={(e) => updateSkill(index, { name: e.target.value })}
                  className="min-w-0 flex-1"
                />
                <Button
                  type="button"
                  size="icon"
                  variant="ghost"
                  aria-label={`${text.removeSkill} ${index + 1}`}
                  disabled={locked}
                  onClick={() =>
                    onChange({
                      ...value,
                      skills: skills.filter((_, i) => i !== index),
                    })
                  }
                >
                  <Trash2 size={15} />
                </Button>
              </div>
              {skill.source_url && (
                <p className="break-all text-xs leading-5 text-gray-500">
                  {text.skillSource}: {skill.source_url}
                </p>
              )}
              {skill.package_id && (
                <p className="break-all text-xs text-gray-500">
                  {text.skillPackageIncluded} · {skill.entrypoint}
                </p>
              )}
              <textarea
                aria-label={`${text.skillContent} ${index + 1}`}
                value={skill.content}
                onChange={(e) =>
                  updateSkill(index, { content: e.target.value })
                }
                rows={6}
                maxLength={128000}
                required
                disabled={locked}
                placeholder={text.skillContentHint}
                className="w-full resize-y rounded-xl border border-gray-200 bg-white p-3 font-mono text-xs leading-6 outline-none focus:border-primary-300 focus:ring-2 focus:ring-primary-100"
              />
            </div>
          ))}
        </div>
      </div>
    </details>
  );
}
