import { PythonOutlined } from "@ant-design/icons";
import { motion } from "framer-motion";
import { LRUCache } from "lru-cache";
import {
    BookOpenText,
    CheckCircle2,
    FileText,
    Globe,
    PencilRuler,
    Search,
    ShieldCheck,
    Wrench,
    XCircle,
} from "lucide-react";
import { useTheme } from "next-themes";
import React, { useMemo } from "react";
import SyntaxHighlighter from "react-syntax-highlighter";
import { docco } from "react-syntax-highlighter/dist/esm/styles/hljs";
import { dark } from "react-syntax-highlighter/dist/esm/styles/prism";

import { FavIcon } from "../../../../components/deep-research/fav-icon";
import Image from "../../../../components/deep-research/image";
import { RainbowText } from "../../../../components/deep-research/rainbow-text";
import { Tooltip } from "../../../../components/deep-research/tooltip";
import {
    Accordion,
    AccordionContent,
    AccordionItem,
    AccordionTrigger,
} from "../../../../components/ui/accordion";
import { Skeleton } from "../../../../components/ui/skeleton";
import { useTranslations } from "../../../../lib/deep-research/i18n";
import { findMCPTool } from "../../../../lib/deep-research/mcp";
import type { ToolCallRuntime } from "../../../../lib/deep-research/messages";
import { parseJSON } from "../../../../lib/deep-research/utils";
import { cn } from "../../../../lib/utils";

const __pageCache = new LRUCache<string, string>({ max: 100 });

function getHostname(url?: string): string {
    if (!url) return "";
    try {
        return new URL(url).hostname.replace(/^www\./, "");
    } catch {
        return url;
    }
}

function ToolCallSection({
    header,
    children,
    bodyClassName,
}: {
    header: React.ReactNode;
    children?: React.ReactNode;
    bodyClassName?: string;
}) {
    return (
        <section className="mt-3 px-4">
            <div className="overflow-hidden rounded-2xl border border-gray-200/70 bg-white shadow-sm">
                <div className="border-b border-gray-100 bg-gray-50/80 px-4 py-3">{header}</div>
                {children ? <div className={cn("px-4 py-3", bodyClassName)}>{children}</div> : null}
            </div>
        </section>
    );
}

type SearchResult =
    | {
        type: "page";
        title: string;
        url: string;
        content: string;
    }
    | {
        type: "image";
        image_url: string;
        image_description: string;
    };

export function WebSearchToolCall({ toolCall }: { toolCall: ToolCallRuntime }) {
    // @ts-ignore - i18n shim
    const t = useTranslations("chat.research");
    const searching = useMemo(() => {
        return toolCall.result === undefined;
    }, [toolCall.result]);
    const searchResults = useMemo<SearchResult[]>(() => {
        let results: SearchResult[] | undefined = undefined;

        try {
            if (toolCall.result) {
                results = parseJSON(toolCall.result, []);
            }
        } catch (error) {
            console.warn("Failed to parse search results:", error);
            results = undefined;
        }

        if (Array.isArray(results)) {
            results.forEach((result) => {
                if (result.type === "page") {
                    __pageCache.set(result.url, result.title);
                }
            });
        } else {
            // If parsing failed, still try to show something useful
            results = [];
        }

        return results;
    }, [toolCall.result]);
    const pageResults = useMemo(
        () => searchResults?.filter((result) => result.type === "page"),
        [searchResults],
    );
    const imageResults = useMemo(
        () => searchResults?.filter((result) => result.type === "image"),
        [searchResults],
    );
    const query = useMemo(() => (toolCall.args as { query: string }).query, [toolCall.args]);

    return (
        <ToolCallSection
            header={(
                <div className="min-w-0">
                    <RainbowText
                        className="flex items-center text-sm font-semibold text-gray-900"
                        animated={searchResults === undefined}
                    >
                        <Search size={16} className="mr-2 text-blue-500" />
                        <span>{t("searchingFor")}</span>
                    </RainbowText>
                    <p className="mt-1 break-words pl-6 text-sm leading-6 text-gray-600">{query}</p>
                </div>
            )}
            bodyClassName="space-y-3"
        >
            {searching && (
                <ul className="grid gap-3 sm:grid-cols-2 xl:grid-cols-3">
                    {[...Array(6)].map((_, i) => (
                        <li key={`search-result-${i}`}>
                            <Skeleton
                                className="h-24 w-full rounded-xl bg-gradient-to-br from-gray-100 to-gray-200"
                                style={{ animationDelay: `${i * 0.15}s` }}
                            />
                        </li>
                    ))}
                </ul>
            )}

            {!!pageResults?.length && (
                <ul className="grid gap-3 sm:grid-cols-2 xl:grid-cols-3">
                    {pageResults.slice(0, 12).map((searchResult, i) => {
                        const shouldAnimate = i < 6;
                        return (
                            <motion.li
                                key={`search-result-${i}`}
                                initial={shouldAnimate ? { opacity: 0, y: 10 } : { opacity: 1, y: 0 }}
                                animate={{ opacity: 1, y: 0 }}
                                transition={shouldAnimate ? {
                                    duration: 0.15,
                                    delay: Math.min(i * 0.05, 0.3),
                                    ease: "easeOut",
                                } : undefined}
                            >
                                <a
                                    className="group flex min-h-[92px] items-start gap-3 rounded-xl border border-gray-200 bg-white px-3 py-3 transition-all hover:border-gray-300 hover:bg-gray-50"
                                    href={searchResult.url}
                                    target="_blank"
                                    rel="noopener noreferrer"
                                >
                                    <FavIcon
                                        className="mt-0.5 shrink-0"
                                        url={searchResult.url}
                                        title={searchResult.title}
                                    />
                                    <div className="min-w-0 flex-1">
                                        <div className="line-clamp-3 text-sm font-medium leading-6 text-gray-900 transition-colors group-hover:text-gray-700">
                                            {searchResult.title}
                                        </div>
                                        <div className="mt-1 truncate text-xs text-gray-500">
                                            {getHostname(searchResult.url)}
                                        </div>
                                    </div>
                                </a>
                            </motion.li>
                        );
                    })}
                </ul>
            )}

            {!!imageResults?.length && (
                <ul className="grid gap-3 sm:grid-cols-2 xl:grid-cols-3">
                    {imageResults.slice(0, 6).map((searchResult, i) => {
                        const shouldAnimate = i < 4;
                        return (
                            <motion.li
                                key={`search-image-${i}`}
                                initial={shouldAnimate ? { opacity: 0, y: 10 } : { opacity: 1, y: 0 }}
                                animate={{ opacity: 1, y: 0 }}
                                transition={shouldAnimate ? {
                                    duration: 0.15,
                                    delay: Math.min(i * 0.05, 0.2),
                                    ease: "easeOut",
                                } : undefined}
                            >
                                <a
                                    className="group block overflow-hidden rounded-xl border border-gray-200 bg-white transition-all hover:border-gray-300 hover:bg-gray-50"
                                    href={searchResult.image_url}
                                    target="_blank"
                                    rel="noopener noreferrer"
                                >
                                    <Image
                                        src={searchResult.image_url}
                                        alt={searchResult.image_description}
                                        className="h-40 w-full bg-gray-100 bg-cover bg-center bg-no-repeat"
                                        imageClassName="group-hover:scale-105"
                                        imageTransition
                                    />
                                    {searchResult.image_description && (
                                        <div className="px-3 py-2 text-xs leading-5 text-gray-600 line-clamp-2">
                                            {searchResult.image_description}
                                        </div>
                                    )}
                                </a>
                            </motion.li>
                        );
                    })}
                </ul>
            )}
        </ToolCallSection>
    );
}

export function CrawlToolCall({ toolCall }: { toolCall: ToolCallRuntime }) {
    // @ts-ignore - i18n shim
    const t = useTranslations("chat.research");
    const url = useMemo(
        () => (toolCall.args as { url: string }).url,
        [toolCall.args],
    );
    const title = useMemo(() => __pageCache.get(url), [url]);
    return (
        <ToolCallSection
            header={(
                <RainbowText
                    className="flex items-center text-sm font-semibold text-gray-900"
                    animated={toolCall.result === undefined}
                >
                    <BookOpenText size={16} className="mr-2 text-emerald-500" />
                    <span>{t("reading")}</span>
                </RainbowText>
            )}
        >
            <motion.a
                className="group flex items-start gap-3 rounded-xl border border-gray-200 bg-white px-3 py-3 transition-all hover:border-gray-300 hover:bg-gray-50"
                href={url}
                target="_blank"
                rel="noopener noreferrer"
                initial={{ opacity: 0, y: 10 }}
                animate={{ opacity: 1, y: 0 }}
                transition={{
                    duration: 0.15,
                    ease: "easeOut",
                }}
            >
                <FavIcon className="mt-0.5 shrink-0" url={url} title={title} />
                <div className="min-w-0 flex-1">
                    <div className="line-clamp-2 text-sm font-medium leading-6 text-gray-900">
                        {title ?? url}
                    </div>
                    <div className="mt-1 truncate text-xs text-gray-500">{getHostname(url)}</div>
                </div>
            </motion.a>
        </ToolCallSection>
    );
}

export function RetrieverToolCall({ toolCall }: { toolCall: ToolCallRuntime }) {
    // @ts-ignore - i18n shim
    const t = useTranslations("chat.research");
    const searching = useMemo(() => {
        return toolCall.result === undefined;
    }, [toolCall.result]);
    const documents = useMemo<
        Array<{ id: string; title: string; content: string }>
    >(() => {
        return toolCall.result ? parseJSON(toolCall.result, []) : [];
    }, [toolCall.result]);
    const keywords = useMemo(() => (toolCall.args as { keywords: string }).keywords, [toolCall.args]);

    return (
        <ToolCallSection
            header={(
                <div className="min-w-0">
                    <RainbowText className="flex items-center text-sm font-semibold text-gray-900" animated={searching}>
                        <Search size={16} className="mr-2 text-violet-500" />
                        <span>{t("retrievingDocuments")}</span>
                    </RainbowText>
                    <p className="mt-1 break-words pl-6 text-sm leading-6 text-gray-600">{keywords}</p>
                </div>
            )}
        >
            <ul className="grid gap-3 sm:grid-cols-2">
                {searching &&
                    [...Array(2)].map((_, i) => (
                        <li key={`search-result-${i}`}>
                            <Skeleton
                                className="h-24 w-full rounded-xl bg-gradient-to-br from-gray-100 to-gray-200"
                                style={{ animationDelay: `${i * 0.2}s` }}
                            />
                        </li>
                    ))}
                {documents?.map((doc, i) => {
                    const shouldAnimate = i < 4;
                    return (
                        <motion.li
                            key={`search-result-${i}`}
                            initial={shouldAnimate ? { opacity: 0, y: 10 } : { opacity: 1, y: 0 }}
                            animate={{ opacity: 1, y: 0 }}
                            transition={shouldAnimate ? {
                                duration: 0.15,
                                delay: Math.min(i * 0.05, 0.2),
                                ease: "easeOut",
                            } : undefined}
                        >
                            <div className="flex min-h-[88px] items-start gap-3 rounded-xl border border-gray-200 bg-white px-3 py-3">
                                <div className="flex h-9 w-9 shrink-0 items-center justify-center rounded-lg bg-gray-100 text-gray-600">
                                    <FileText size={18} />
                                </div>
                                <div className="min-w-0 flex-1">
                                    <div className="line-clamp-2 text-sm font-medium leading-6 text-gray-900">{doc.title}</div>
                                    <div className="mt-1 text-xs text-gray-500">
                                        {t("retrievedChunkInfo", { chunk: i + 1, size: doc.content.length })}
                                    </div>
                                </div>
                            </div>
                        </motion.li>
                    );
                })}
            </ul>
        </ToolCallSection>
    );
}

export function PythonToolCall({ toolCall }: { toolCall: ToolCallRuntime }) {
    // @ts-ignore - i18n shim
    const t = useTranslations("chat.research");
    const code = useMemo<string | undefined>(() => {
        return (toolCall.args as { code?: string }).code;
    }, [toolCall.args]);
    const { resolvedTheme } = useTheme();
    return (
        <ToolCallSection
            header={(
                <div className="flex items-center text-sm font-semibold text-gray-900">
                    <PythonOutlined className="mr-2" />
                    <RainbowText animated={toolCall.result === undefined}>
                        {t("runningPythonCode")}
                    </RainbowText>
                </div>
            )}
            bodyClassName="space-y-4"
        >
            <div className="max-h-[400px] overflow-y-auto rounded-xl bg-gray-950 p-2 text-sm">
                    <SyntaxHighlighter
                        language="python"
                        style={resolvedTheme === "dark" ? dark : docco}
                        customStyle={{
                            background: "transparent",
                            border: "none",
                            boxShadow: "none",
                        }}
                    >
                        {code?.trim() ?? ""}
                    </SyntaxHighlighter>
            </div>
            {toolCall.result && <PythonToolCallResult result={toolCall.result} />}
        </ToolCallSection>
    );
}

export function PythonToolCallResult({ result }: { result: string }) {
    // @ts-ignore - i18n shim
    const t = useTranslations("chat.research");
    const { resolvedTheme } = useTheme();
    const hasError = useMemo(
        () => result.includes("Error executing code:\n"),
        [result],
    );
    const error = useMemo(() => {
        if (hasError) {
            const parts = result.split("```\nError: ");
            if (parts.length > 1) {
                return parts[1]!.trim();
            }
        }
        return null;
    }, [result, hasError]);
    const stdout = useMemo(() => {
        if (!hasError) {
            const parts = result.split("```\nStdout: ");
            if (parts.length > 1) {
                return parts[1]!.trim();
            }
        }
        return null;
    }, [result, hasError]);
    return (
        <>
            <div className="text-sm font-semibold text-gray-900">
                {hasError ? t("errorExecutingCode") : t("executionOutput")}
            </div>
            <div className="max-h-[400px] overflow-y-auto rounded-xl border border-gray-200 bg-gray-50 p-2 text-sm">
                <SyntaxHighlighter
                    language="plaintext"
                    style={resolvedTheme === "dark" ? dark : docco}
                    customStyle={{
                        color: hasError ? "red" : "inherit",
                        background: "transparent",
                        border: "none",
                        boxShadow: "none",
                    }}
                >
                    {error ?? stdout ?? t("emptyOutput")}
                </SyntaxHighlighter>
            </div>
        </>
    );
}

// Friendly display names and icons for known tool functions
export const TOOL_DISPLAY_MAP: Record<
    string,
    { labelKey: string; icon: React.ReactNode; descriptionKey: string }
> = {
    validate_url: {
        labelKey: "toolLabelValidateUrl",
        icon: <ShieldCheck size={16} className="mr-2 text-blue-500" />,
        descriptionKey: "toolDescriptionValidateUrl",
    },
    crawl_tool: {
        labelKey: "toolLabelCrawlTool",
        icon: <Globe size={16} className="mr-2 text-green-500" />,
        descriptionKey: "toolDescriptionCrawlTool",
    },
    web_search: {
        labelKey: "toolLabelWebSearch",
        icon: <Search size={16} className="mr-2 text-purple-500" />,
        descriptionKey: "toolDescriptionWebSearch",
    },
    python_repl_tool: {
        labelKey: "toolLabelPythonReplTool",
        icon: <Wrench size={16} className="mr-2 text-orange-500" />,
        descriptionKey: "toolDescriptionPythonReplTool",
    },
};

export function getToolDisplay(
    toolName: string,
    t: (key: string, params?: Record<string, unknown>) => string,
) {
    if (TOOL_DISPLAY_MAP[toolName]) {
        const toolDisplay = TOOL_DISPLAY_MAP[toolName];
        return {
            label: t(toolDisplay.labelKey),
            icon: toolDisplay.icon,
            description: t(toolDisplay.descriptionKey),
        };
    }
    // Generate a friendly name from snake_case function name
    const friendlyName = toolName
        .replace(/_/g, " ")
        .replace(/\b\w/g, (c) => c.toUpperCase());
    return {
        label: friendlyName,
        icon: <PencilRuler size={16} className="mr-2 text-gray-500" />,
        description: t("toolDescriptionRunningTool", { toolName }),
    };
}

/** Try to render a user-friendly summary from tool call result JSON */
export function MCPToolResultSummary({ result }: { result: string }) {
    // @ts-ignore - i18n shim
    const t = useTranslations("chat.research");
    const parsed = useMemo(() => {
        try {
            return JSON.parse(result);
        } catch {
            return null;
        }
    }, [result]);

    if (!parsed || typeof parsed !== "object") {
        // Fallback: show truncated raw text
        return (
            <p className="text-muted-foreground text-sm">
                {result.length > 200 ? result.slice(0, 200) + "…" : result}
            </p>
        );
    }

    // Handle validate_url style results: { url, is_valid, ... }
    if ("is_valid" in parsed || "is_accessible" in parsed) {
        const isValid = parsed.is_valid ?? parsed.is_accessible ?? parsed.success;
        const url = parsed.url ?? parsed.link ?? "";
        return (
            <div className="flex items-center gap-2 text-sm">
                {isValid ? (
                    <CheckCircle2 size={14} className="shrink-0 text-green-500" />
                ) : (
                    <XCircle size={14} className="shrink-0 text-red-500" />
                )}
                <span className={isValid ? "text-green-600 dark:text-green-400" : "text-red-600 dark:text-red-400"}>
                    {isValid ? t("sourceVerified") : t("sourceUnavailable")}
                </span>
                {url && (
                    <span className="text-muted-foreground max-w-[400px] truncate text-xs">
                        {url}
                    </span>
                )}
            </div>
        );
    }

    // Handle results with a "content" or "text" or "result" field
    const textContent =
        parsed.content ?? parsed.text ?? parsed.result ?? parsed.output ?? parsed.answer;
    if (typeof textContent === "string" && textContent) {
        return (
            <p className="text-muted-foreground text-sm">
                {textContent.length > 300 ? textContent.slice(0, 300) + "…" : textContent}
            </p>
        );
    }

    // Handle results with a "title" field (e.g. search results)
    if (parsed.title) {
        return (
            <p className="text-muted-foreground text-sm">
                <span className="font-medium">{parsed.title}</span>
                {parsed.description && (
                    <span className="ml-1">{parsed.description}</span>
                )}
            </p>
        );
    }

    // Fallback: show key count
    const keys = Object.keys(parsed);
    return (
        <p className="text-muted-foreground text-sm">
            {t("returnedFields", { count: keys.length, fields: keys.slice(0, 5).join(", ") })}
            {keys.length > 5 ? "…" : ""}
        </p>
    );
}

export function MCPToolCall({ toolCall }: { toolCall: ToolCallRuntime }) {
    // @ts-ignore - i18n shim
    const t = useTranslations("chat.research");
    const tool = useMemo(() => findMCPTool(toolCall.name), [toolCall.name]);
    const display = useMemo(() => getToolDisplay(toolCall.name, t), [toolCall.name, t]);
    const { resolvedTheme } = useTheme();
    const isRunning = toolCall.result === undefined;

    return (
        <section className="mt-3 px-4">
            <div className="w-fit overflow-y-auto rounded-2xl border border-gray-200/70 bg-white px-4 py-2 shadow-sm">
                <Accordion type="single" collapsible className="w-full">
                    <AccordionItem value="item-1">
                        <AccordionTrigger>
                            <Tooltip title={tool?.description ?? display.description}>
                                <div className="flex items-center font-medium">
                                    {display.icon}
                                    <RainbowText
                                        className="pr-0.5 text-base font-medium"
                                        animated={isRunning}
                                    >
                                        {isRunning ? display.label + "…" : display.label}
                                    </RainbowText>
                                </div>
                            </Tooltip>
                        </AccordionTrigger>
                        <AccordionContent>
                            {toolCall.result && (
                                <div className="space-y-2">
                                    {/* Friendly summary */}
                                    <div className="bg-muted/50 rounded-md px-3 py-2">
                                        <MCPToolResultSummary result={toolCall.result.trim()} />
                                    </div>
                                    {/* Raw JSON details (collapsed) */}
                                    <details className="group">
                                        <summary className="text-muted-foreground cursor-pointer text-xs hover:underline">
                                            {t("showRawData")}
                                        </summary>
                                        <div className="bg-accent mt-1 max-h-[300px] max-w-[560px] overflow-y-auto rounded-md text-sm">
                                            <SyntaxHighlighter
                                                language="json"
                                                style={resolvedTheme === "dark" ? dark : docco}
                                                customStyle={{
                                                    background: "transparent",
                                                    border: "none",
                                                    boxShadow: "none",
                                                }}
                                            >
                                                {toolCall.result.trim()}
                                            </SyntaxHighlighter>
                                        </div>
                                    </details>
                                </div>
                            )}
                        </AccordionContent>
                    </AccordionItem>
                </Accordion>
            </div>
        </section>
    );
}
