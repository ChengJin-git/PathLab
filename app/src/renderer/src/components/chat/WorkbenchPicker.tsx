import {
  forwardRef,
  useEffect,
  useImperativeHandle,
  useRef,
  useState,
} from "react";
import { ChevronRight, Loader2 } from "lucide-react";
import { useTranslation } from "react-i18next";
import {
  commandLanguage,
  localizePrimaryCommand,
} from "../../locales/commands";
import {
  searchCommands,
  searchResources,
  type ResourceItem,
  type ResourceKind,
  type WorkbenchCommand,
} from "../../api/workbench";
import { useWorkbenchText } from "./workbenchText";

export function completionToken(value: string, caret: number) {
  const before = value.slice(0, caret);
  const match = /(?:^|[\s\p{Script=Han}])([@/])([^\s@/]{0,120})$/u.exec(before);
  if (!match || (match[1] === "/" && before.slice(0, match.index).trim()))
    return null;
  return {
    trigger: match[1],
    query: match[2],
    start: caret - match[2].length - 1,
    end: caret,
  };
}

export const PRIMARY_COMMANDS: WorkbenchCommand[] = [
  {
    id: "experiment",
    name: "自主探索",
    description: "",
    skill_id: "pathlab-research",
    mode: "research",
  },
  {
    id: "literature",
    name: "文献研究",
    description: "",
    skill_id: "nature-literature-pipeline",
    mode: "research",
  },
  {
    id: "analyze",
    name: "结果分析",
    description: "",
    skill_id: "nature-statistics",
    mode: "research",
  },
  {
    id: "report",
    name: "研究报告",
    description: "",
    skill_id: "nature-writing",
    mode: "research",
  },
  {
    id: "ask",
    name: "讨论",
    description: "",
    mode: "chat",
  },
];

export interface PickerHandle {
  keyDown(event: React.KeyboardEvent): boolean;
}
interface Props {
  value: string;
  caret: number;
  composing: boolean;
  workspaceId?: string | null;
  conversationId?: string | null;
  sessionId?: string;
  disabled?: boolean;
  onChange: (value: string, caret: number) => void;
  canExecute?: boolean;
  onCommand: (command: WorkbenchCommand) => void;
  onReference: (item: ResourceItem) => void;
}

export const WorkbenchPicker = forwardRef<PickerHandle, Props>(
  function WorkbenchPicker(props, ref) {
    const text = useWorkbenchText();
    const { i18n } = useTranslation();
    const language = commandLanguage(i18n.language);
    const token = completionToken(props.value, props.caret);
    const identity = token
      ? `${token.trigger}:${token.start}:${token.query}`
      : "";
    const [dismissed, setDismissed] = useState("");
    useEffect(() => {
      if (!token) setDismissed("");
    }, [identity]);
    const open =
      !!token && !props.composing && !props.disabled && dismissed !== identity;
    const [kind, setKind] = useState<ResourceKind>("dataset");
    const [dataset, setDataset] = useState<ResourceItem>();
    const [parent, setParent] = useState("");
    const [commands, setCommands] = useState(() =>
      PRIMARY_COMMANDS.map((c) => localizePrimaryCommand(c, language)),
    );
    const [resources, setResources] = useState<ResourceItem[]>([]);
    const [cursor, setCursor] = useState("");
    const [next, setNext] = useState<string | null>(null);
    const [active, setActive] = useState(0);
    const [busy, setBusy] = useState(false);
    const [error, setError] = useState("");
    const generation = useRef(0);
    const [libraryRevision,setLibraryRevision]=useState(0);
    useEffect(()=>{const changed=()=>setLibraryRevision(value=>value+1);window.addEventListener('capabilities:changed',changed);return()=>window.removeEventListener('capabilities:changed',changed)},[]);
    const resetKey = `${identity}:${language}:${kind}:${dataset?.id}:${parent}:${props.workspaceId}:${props.conversationId}`;
    useEffect(() => {
      setCursor("");
      setNext(null);
      setActive(0);
    }, [resetKey]);
    useEffect(() => {
      setDataset(undefined);
      setParent("");
      setKind("dataset");
    }, [props.workspaceId, props.conversationId]);
    useEffect(() => {
      if (!open || !token) return;
      const controller = new AbortController();
      const request = ++generation.current;
      setBusy(true);
      setError("");
      setNext(null);
      if (token.trigger === "/")
        setCommands(
          PRIMARY_COMMANDS.map((c) =>
            localizePrimaryCommand(c, language),
          ).filter((c) =>
            `${c.id} ${c.name} ${c.description}`
              .toLowerCase()
              .includes(token.query.toLowerCase()),
          ),
        );
      else setResources([]);
      const timer = window.setTimeout(
        async () => {
          try {
            if (token.trigger === "/") {
              const page = await searchCommands(
                token.query,
                cursor,
                controller.signal,
                language,
              );
              if (
                request === generation.current &&
                !controller.signal.aborted
              ) {
                setCommands(page.items);
                setNext(page.next_cursor);
              }
            } else {
              const params: Record<string, string> = {
                kind,
                q: token.query,
                cursor,
              };
              if (props.workspaceId) params.workspace_id = props.workspaceId;
              if (kind === "slide" && dataset) params.dataset_id = dataset.id;
              const page = await searchResources(params, controller.signal);
              if (
                request === generation.current &&
                !controller.signal.aborted
              ) {
                setResources(page.items);
                setNext(page.next_cursor);
              }
            }
          } catch (e) {
            if (!controller.signal.aborted && request === generation.current)
              setError((e as Error).message);
          } finally {
            if (!controller.signal.aborted && request === generation.current)
              setBusy(false);
          }
        },
        token.trigger === "/" && !token.query ? 0 : 180,
      );
      return () => {
        clearTimeout(timer);
        controller.abort();
        generation.current++;
      };
    }, [
      open,
      identity,
      language,
      cursor,
      kind,
      dataset?.id,
      parent,
      props.workspaceId,
      props.conversationId,
      props.sessionId,
      libraryRevision,
    ]);

    const items = token?.trigger === "/" ? commands : resources;
    const select = (index: number) => {
      if (!token || !items[index]) return;
      if (token.trigger === "/") {
        const command = commands[index];
        if (
          command.available === false ||
          (command.mode === "research" && props.canExecute === false)
        )
          return;
        props.onCommand(command);
      } else {
        const item = resources[index];
        if (item.entry_kind === "directory") {
          setParent(item.path || "");
          props.onChange(
            props.value.slice(0, token.start) +
              "@" +
              props.value.slice(token.end),
            token.start + 1,
          );
          return;
        }
        props.onReference(item);
      }
      props.onChange(
        props.value.slice(0, token.start) + props.value.slice(token.end),
        token.start,
      );
      setDismissed(identity);
    };
    useImperativeHandle(ref, () => ({
      keyDown(event) {
        if (!open || event.nativeEvent.isComposing) return false;
        if (event.key === "Escape") {
          setDismissed(identity);
          event.preventDefault();
          return true;
        }
        if (event.key === "ArrowDown" || event.key === "ArrowUp") {
          setActive((a) =>
            Math.max(
              0,
              Math.min(
                items.length - 1,
                a + (event.key === "ArrowDown" ? 1 : -1),
              ),
            ),
          );
          event.preventDefault();
          return true;
        }
        if ((event.key === "Enter" || event.key === "Tab") && items.length) {
          select(active);
          event.preventDefault();
          return true;
        }
        return false;
      },
    }));
    if (!open || !token) return null;
    return (
      <section
        className="mb-2 overflow-hidden rounded-xl border border-gray-200 bg-white shadow-sm"
        aria-label={text(token.trigger === "/" ? "skills" : "resources")}
      >
        <div className="flex flex-wrap items-center gap-1 border-b p-2 text-xs text-gray-500">
          {token.trigger === "@" ? (
            <>
              {(
                [
                  "dataset",
                  "task",
                  "model",
                  "file",
                   "research",
                   "conversation",
                ] as ResourceKind[]
              ).map((k) => (
                <button
                  type="button"
                  key={k}
                  onClick={() => {
                    setKind(k);
                    setDataset(undefined);
                    setParent("");
                  }}
                  className={`rounded px-2 py-1 ${kind === k ? "bg-gray-100 text-gray-950" : "hover:bg-gray-50"}`}
                >
                  {text(k)}
                </button>
              ))}
              {dataset && (
                <button
                  type="button"
                  onClick={() => setKind("slide")}
                  className="max-w-44 truncate rounded bg-blue-50 px-2 py-1 text-blue-700"
                >
                  {dataset.name}
                </button>
              )}
              {parent && (
                <button
                  type="button"
                  onClick={() =>
                    setParent(parent.split("/").slice(0, -1).join("/"))
                  }
                >
                  ../{parent}
                </button>
              )}
            </>
          ) : (
            <span className="px-2">{text("skills")}</span>
          )}
          {busy && <Loader2 size={13} className="ml-auto animate-spin" />}
        </div>
        {token.trigger === '@' && kind === 'conversation' && <p className="px-3 py-2 text-xs text-gray-500">{text('conversationReferenceHint')}</p>}
        <div
          role="listbox"
          aria-label={text("resources")}
          className="max-h-56 overflow-y-auto p-1"
        >
          {items.map((item, index) => (
            <div key={item.id} className="flex items-center">
              <button
                type="button"
                role="option"
                aria-selected={active === index}
                disabled={
                  ("available" in item && item.available === false) ||
                  ("mode" in item &&
                    item.mode === "research" &&
                    props.canExecute === false)
                }
                onMouseEnter={() => setActive(index)}
                onClick={() => select(index)}
                className={`min-w-0 flex-1 rounded-lg px-3 py-2 text-left text-sm disabled:opacity-40 ${active === index ? "bg-gray-100" : "hover:bg-gray-50"}`}
              >
                <span className="block truncate">
                  {token.trigger === "/"
                    ? ('library_skill_id' in item && item.id.startsWith('ugc-') ? item.name : `/${item.id} · ${item.name}`)
                    : item.name}
                </span>
                {'source_title' in item&&item.source_title&&<span className="block truncate text-xs text-slate-400">{item.source_title}</span>}
                {"description" in item && item.description && (
                  <span
                    title={item.description}
                    className="block line-clamp-2 text-xs leading-5 text-gray-500"
                  >
                    {item.description}
                  </span>
                )}
              </button>
              {token.trigger === "@" && kind === "dataset" && (
                <button
                  type="button"
                  aria-label={`${text("browse")} ${item.name}`}
                  onClick={() => {
                    setDataset(item as ResourceItem);
                    setKind("slide");
                    props.onChange(
                      props.value.slice(0, token.start) +
                        "@" +
                        props.value.slice(token.end),
                      token.start + 1,
                    );
                  }}
                  className="p-2 text-gray-500"
                >
                  <ChevronRight size={16} />
                </button>
              )}
            </div>
          ))}
          {!items.length && !busy && (
            <p className="px-3 py-4 text-xs text-gray-500">
              {error || text("empty")}
            </p>
          )}
        </div>
        <div className="flex items-center justify-between border-t px-3 py-2 text-xs text-gray-400">
          <span>
            {token.trigger === "@" ? text("prefix") : "↑ ↓ · Enter · Esc"}
          </span>
          {next && (
            <button
              type="button"
              disabled={busy}
              onClick={() => {
                setCursor(next);
                setActive(0);
              }}
              className="shrink-0 pl-2 text-blue-600"
            >
              {text("more")}
            </button>
          )}
        </div>
      </section>
    );
  },
);
