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
import type { Message, ToolCallRuntime } from "../../../../lib/deep-research/messages";
import {
    extractToolResultData,
    extractToolResultItems,
    getToolResultReason,
    getToolResultStatus,
    getToolResultSummary,
    safeParseToolResult,
} from "../../../../lib/deep-research/utils/tool-result";
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

type WebSearchState =
    | "searching"
    | "completed"
    | "no_results"
    | "no_useful_information"
    | "error";

function getSearchSnippet(content?: string): string {
    if (!content) return "";
    return content.replace(/\s+/g, " ").trim();
}

function SearchStatusBadge({
    status,
    t,
}: {
    status: WebSearchState;
    t: (key: string, params?: Record<string, unknown>) => string;
}) {
    const statusConfig = {
        searching: {
            label: t("searchStatusSearching"),
            className: "border-blue-100 bg-blue-50 text-blue-700",
        },
        completed: {
            label: t("searchStatusCompleted"),
            className: "border-emerald-100 bg-emerald-50 text-emerald-700",
        },
        no_results: {
            label: t("searchStatusNoResults"),
            className: "border-gray-200 bg-white text-gray-600",
        },
        no_useful_information: {
            label: t("searchStatusNoUsefulInfo"),
            className: "border-amber-100 bg-amber-50 text-amber-700",
        },
        error: {
            label: t("searchStatusError"),
            className: "border-red-100 bg-red-50 text-red-700",
        },
    } satisfies Record<WebSearchState, { label: string; className: string }>;
    const config = statusConfig[status];

    return (
        <span
            className={cn(
                "inline-flex items-center rounded-full border px-2.5 py-1 text-xs font-medium",
                config.className,
            )}
        >
            {config.label}
        </span>
    );
}

function ToolResultNotice({
    status,
    title,
    description,
}: {
    status: "no_results" | "no_useful_information" | "error";
    title: string;
    description: string;
}) {
    const icon = status === "error"
        ? <XCircle size={18} className="text-red-500" />
        : status === "no_useful_information"
            ? <Search size={18} className="text-amber-500" />
            : <Search size={18} className="text-gray-400" />;

    return (
        <div className="flex items-start gap-3 rounded-xl border border-dashed border-gray-200 bg-gray-50/80 px-4 py-3">
            <div className="mt-0.5">{icon}</div>
            <div className="min-w-0">
                <div className="text-sm font-medium text-gray-800">{title}</div>
                <div className="mt-1 text-xs leading-5 text-gray-500">{description}</div>
            </div>
        </div>
    );
}

function getSearchEmptyCopy(
    status: Exclude<WebSearchState, "searching" | "completed">,
    t: (key: string, params?: Record<string, unknown>) => string,
    summary?: string,
) {
    if (status === "error") {
        return {
            title: t("searchStatusError"),
            description: summary || t("searchErrorDescription"),
        };
    }
    if (status === "no_useful_information") {
        return {
            title: t("searchStatusNoUsefulInfo"),
            description: summary || t("searchNoUsefulInfoDescription"),
        };
    }
    return {
        title: t("searchStatusNoResults"),
        description: summary || t("searchEmptyDescription"),
    };
}

function getGenericToolCopy(
    status: "success" | "no_results" | "no_useful_information" | "error",
    reason: string | undefined,
    t: (key: string, params?: Record<string, unknown>) => string,
    summary?: string,
) {
    const reasonDescription = (() => {
        switch (reason) {
            case "api_unavailable":
            case "http_error":
            case "request_failed":
            case "provider_error":
                return t("toolReasonApiUnavailable");
            case "no_matches":
                return t("toolReasonNoMatches");
            case "empty_account":
                return t("toolReasonEmptyAccount");
            case "missing_snippets":
                return t("toolReasonMissingSnippets");
            case "only_images":
                return t("toolReasonOnlyImages");
            case "insufficient_content":
            case "insufficient_documents":
                return t("toolReasonInsufficientContent");
            case "pdf_not_supported":
                return t("toolReasonPdfNotSupported");
            case "validation_failed":
                return t("toolReasonValidationFailed");
            default:
                return summary;
        }
    })();

    if (status === "error") {
        return {
            label: t("toolStatusErrorGeneric"),
            description: reasonDescription || summary,
        };
    }
    if (status === "no_useful_information") {
        return {
            label: t("toolStatusNoUsefulInfoGeneric"),
            description: reasonDescription || summary,
        };
    }
    if (status === "no_results") {
        return {
            label: t("toolStatusNoResultsGeneric"),
            description: reasonDescription || summary,
        };
    }
    return {
        label: t("toolStatusCompletedGeneric"),
        description: reasonDescription || summary,
    };
}

function SearchResultSkeletonCard({ index }: { index: number }) {
    return (
        <div
            className="rounded-2xl border border-gray-200/80 bg-white px-3 py-3 shadow-sm"
            style={{ animationDelay: `${index * 0.08}s` }}
        >
            <div className="flex items-start gap-3">
                <Skeleton className="h-9 w-9 shrink-0 rounded-xl bg-gray-100" />
                <div className="min-w-0 flex-1 space-y-2">
                    <Skeleton className="h-4 w-5/6 rounded-md bg-gray-100" />
                    <Skeleton className="h-4 w-2/3 rounded-md bg-gray-100" />
                    <Skeleton className="h-3 w-1/3 rounded-md bg-gray-100" />
                </div>
            </div>
        </div>
    );
}

function SearchEmptyState({
    title,
    description,
}: {
    title: string;
    description: string;
}) {
    return (
        <div className="flex min-h-[112px] flex-col items-center justify-center rounded-2xl border border-dashed border-gray-200 bg-gray-50/70 px-6 py-8 text-center">
            <div className="flex h-10 w-10 items-center justify-center rounded-full bg-white text-gray-400 shadow-sm ring-1 ring-gray-200">
                <Search size={18} />
            </div>
            <div className="mt-3 text-sm font-medium text-gray-700">{title}</div>
            <div className="mt-1 text-xs leading-5 text-gray-500">{description}</div>
        </div>
    );
}

export function WebSearchToolCall({
    toolCall,
    messageIsStreaming = false,
    messageFinishReason,
}: {
    toolCall: ToolCallRuntime;
    messageIsStreaming?: boolean;
    messageFinishReason?: Message["finishReason"];
}) {
    // @ts-ignore - i18n shim
    const t = useTranslations("chat.research");
    const query = useMemo(() => {
        const maybeQuery = (toolCall.args as { query?: unknown } | undefined)?.query;
        return typeof maybeQuery === "string" ? maybeQuery : "";
    }, [toolCall.args]);
    const resultStatus = useMemo(
        () => getToolResultStatus(toolCall.result, toolCall.status),
        [toolCall.result, toolCall.status],
    );
    const resultSummary = useMemo(() => getToolResultSummary(toolCall.result), [toolCall.result]);
    const searchResults = useMemo<SearchResult[]>(() => {
        const rawResults = extractToolResultItems<Record<string, unknown>>(toolCall.result);
        const normalized = rawResults.flatMap((result) => {
            if (result.type === "image" && typeof result.image_url === "string") {
                return [{
                    type: "image" as const,
                    image_url: result.image_url,
                    image_description: typeof result.image_description === "string" ? result.image_description : "",
                }];
            }
            if (typeof result.url === "string") {
                return [{
                    type: "page" as const,
                    title: typeof result.title === "string" ? result.title : t("untitledSource"),
                    url: result.url,
                    content: typeof result.content === "string" ? result.content : "",
                }];
            }
            return [];
        });
        normalized.forEach((result) => {
            if (result.type === "page") {
                __pageCache.set(result.url, result.title);
            }
        });
        return normalized;
    }, [toolCall.result]);
    const pageResults = useMemo(
        () => searchResults?.filter((result) => result.type === "page"),
        [searchResults],
    );
    const imageResults = useMemo(
        () => searchResults?.filter((result) => result.type === "image"),
        [searchResults],
    );
    const visibleResultCount = pageResults.length + imageResults.length;
    const hasResultPayload = toolCall.result !== undefined;
    const awaitingToolResult = messageIsStreaming || messageFinishReason === "tool_calls";
    const searchState = useMemo<WebSearchState>(() => {
        if (!hasResultPayload) {
            return awaitingToolResult ? "searching" : "completed";
        }
        if (resultStatus === "error") return "error";
        if (resultStatus === "no_useful_information") return "no_useful_information";
        if (resultStatus === "no_results") return "no_results";
        return visibleResultCount > 0 ? "completed" : "no_results";
    }, [awaitingToolResult, hasResultPayload, resultStatus, visibleResultCount]);
    const resultMeta = useMemo(() => {
        if (searchState !== "completed" || visibleResultCount === 0) return null;
        return t("searchSourceCount", { count: visibleResultCount });
    }, [searchState, t, visibleResultCount]);
    const emptyCopy = useMemo(
        () => searchState === "searching" || searchState === "completed"
            ? null
            : getSearchEmptyCopy(searchState, t, resultSummary),
        [resultSummary, searchState, t],
    );

    return (
        <ToolCallSection
            header={(
                <div className="flex items-start justify-between gap-3">
                    <div className="min-w-0">
                        <RainbowText
                            className="flex items-center text-sm font-semibold text-gray-900"
                            animated={searchState === "searching"}
                        >
                            <Search size={16} className="mr-2 text-blue-500" />
                            <span>{t("searchingFor")}</span>
                        </RainbowText>
                        {query && <p className="mt-1 break-words pl-6 text-sm leading-6 text-gray-600">{query}</p>}
                    </div>
                    <div className="flex shrink-0 flex-col items-end gap-1 pt-0.5">
                        <SearchStatusBadge status={searchState} t={t} />
                        {resultMeta && <span className="text-xs text-gray-500">{resultMeta}</span>}
                    </div>
                </div>
            )}
            bodyClassName="space-y-3"
        >
            {searchState === "searching" && (
                <ul className="grid gap-3 sm:grid-cols-2 xl:grid-cols-3">
                    {[...Array(3)].map((_, i) => (
                        <li key={`search-result-${i}`}>
                            <SearchResultSkeletonCard index={i} />
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
                                    className="group flex min-h-[112px] items-start gap-3 rounded-2xl border border-gray-200/80 bg-white px-3.5 py-3.5 shadow-sm transition-all hover:-translate-y-0.5 hover:border-gray-300 hover:shadow-md"
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
                                        <div className="line-clamp-2 text-sm font-medium leading-6 text-gray-900 transition-colors group-hover:text-gray-700">
                                            {searchResult.title}
                                        </div>
                                        <div className="mt-1 inline-flex max-w-full items-center rounded-full bg-gray-100 px-2 py-0.5 text-[11px] text-gray-600">
                                            <span className="truncate">{getHostname(searchResult.url)}</span>
                                        </div>
                                        {getSearchSnippet(searchResult.content) && (
                                            <div className="mt-2 line-clamp-2 text-xs leading-5 text-gray-500">
                                                {getSearchSnippet(searchResult.content)}
                                            </div>
                                        )}
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

            {emptyCopy && hasResultPayload && visibleResultCount === 0 && (
                <SearchEmptyState
                    title={emptyCopy.title}
                    description={emptyCopy.description}
                />
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
    const crawlData = useMemo(
        () => extractToolResultData<{ url?: string; crawled_content?: string; content_length?: number }>(toolCall.result),
        [toolCall.result],
    );
    const crawlStatus = useMemo(
        () => getToolResultStatus(toolCall.result, toolCall.status),
        [toolCall.result, toolCall.status],
    );
    const crawlSummary = useMemo(() => getToolResultSummary(toolCall.result), [toolCall.result]);
    const displayUrl = crawlData?.url || url;
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
            <div className="space-y-3">
            <motion.a
                className="group flex items-start gap-3 rounded-xl border border-gray-200 bg-white px-3 py-3 transition-all hover:border-gray-300 hover:bg-gray-50"
                href={displayUrl}
                target="_blank"
                rel="noopener noreferrer"
                initial={{ opacity: 0, y: 10 }}
                animate={{ opacity: 1, y: 0 }}
                transition={{
                    duration: 0.15,
                    ease: "easeOut",
                }}
            >
                <FavIcon className="mt-0.5 shrink-0" url={displayUrl} title={title} />
                <div className="min-w-0 flex-1">
                    <div className="line-clamp-2 text-sm font-medium leading-6 text-gray-900">
                        {title ?? displayUrl}
                    </div>
                    <div className="mt-1 truncate text-xs text-gray-500">{getHostname(displayUrl)}</div>
                </div>
            </motion.a>
            {crawlStatus === "no_useful_information" && (
                <ToolResultNotice
                    status="no_useful_information"
                    title={t("crawlStatusNoUsefulInfo")}
                    description={crawlSummary || t("crawlNoUsefulInfoDescription")}
                />
            )}
            {crawlStatus === "error" && (
                <ToolResultNotice
                    status="error"
                    title={t("crawlStatusError")}
                    description={crawlSummary || t("crawlErrorDescription")}
                />
            )}
            </div>
        </ToolCallSection>
    );
}

export function RetrieverToolCall({ toolCall }: { toolCall: ToolCallRuntime }) {
    // @ts-ignore - i18n shim
    const t = useTranslations("chat.research");
    const searching = useMemo(() => {
        return toolCall.result === undefined;
    }, [toolCall.result]);
    const retrievalStatus = useMemo(
        () => getToolResultStatus(toolCall.result, toolCall.status),
        [toolCall.result, toolCall.status],
    );
    const retrievalSummary = useMemo(() => getToolResultSummary(toolCall.result), [toolCall.result]);
    const documents = useMemo<
        Array<{ id: string; title: string; content: string }>
    >(() => {
        return extractToolResultItems<{ id: string; title: string; content: string }>(toolCall.result);
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
            {!searching && documents.length === 0 && retrievalStatus === "no_results" && (
                <SearchEmptyState
                    title={t("retrievalStatusNoResults")}
                    description={retrievalSummary || t("retrievalEmptyDescription")}
                />
            )}
            {!searching && documents.length === 0 && retrievalStatus === "no_useful_information" && (
                <SearchEmptyState
                    title={t("retrievalStatusNoUsefulInfo")}
                    description={retrievalSummary || t("retrievalNoUsefulInfoDescription")}
                />
            )}
            {!searching && documents.length === 0 && retrievalStatus === "error" && (
                <SearchEmptyState
                    title={t("retrievalStatusError")}
                    description={retrievalSummary || t("retrievalErrorDescription")}
                />
            )}
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
    const parsed = useMemo(() => safeParseToolResult(result), [result]);
    const data = useMemo(() => extractToolResultData(result), [result]);
    const items = useMemo(() => extractToolResultItems(result), [result]);
    const status = useMemo(() => getToolResultStatus(result), [result]);
    const reason = useMemo(() => getToolResultReason(result), [result]);
    const summary = useMemo(() => getToolResultSummary(result), [result]);

    if (!parsed || typeof parsed !== "object") {
        // Fallback: show truncated raw text
        return (
            <p className="text-muted-foreground text-sm">
                {result.length > 200 ? result.slice(0, 200) + "…" : result}
            </p>
        );
    }

    // Handle validate_url style results: { url, is_valid, ... }
    if (data && typeof data === "object" && ("is_valid" in data || "is_accessible" in data)) {
        const isValid = (data as Record<string, unknown>).is_valid
            ?? (data as Record<string, unknown>).is_accessible
            ?? (data as Record<string, unknown>).success;
        const url = ((data as Record<string, unknown>).url ?? (data as Record<string, unknown>).link ?? "") as string;
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

    if (status && summary) {
        const copy = getGenericToolCopy(status, reason, t, summary);
        const icon = status === "error"
            ? <XCircle size={14} className="shrink-0 text-red-500" />
            : status === "no_useful_information"
                ? <Search size={14} className="shrink-0 text-amber-500" />
                : status === "no_results"
                    ? <Search size={14} className="shrink-0 text-gray-400" />
                    : <CheckCircle2 size={14} className="shrink-0 text-green-500" />;
        return (
            <div className="flex items-start gap-2 text-sm">
                {icon}
                <div className="min-w-0">
                    <div className="text-muted-foreground">{copy.label}</div>
                    {copy.description && (
                        <div className="text-muted-foreground text-xs leading-5">{copy.description}</div>
                    )}
                    {items.length > 0 && (
                        <div className="text-muted-foreground text-xs">
                            {t("returnedItemsCount", { count: items.length })}
                        </div>
                    )}
                </div>
            </div>
        );
    }

    // Handle results with a "content" or "text" or "result" field
    const record = parsed as Record<string, unknown>;
    const textContent =
        record.content ?? record.text ?? record.result ?? record.output ?? record.answer;
    if (typeof textContent === "string" && textContent) {
        return (
            <p className="text-muted-foreground text-sm">
                {textContent.length > 300 ? textContent.slice(0, 300) + "…" : textContent}
            </p>
        );
    }

    // Handle results with a "title" field (e.g. search results)
    if (record.title) {
        return (
            <p className="text-muted-foreground text-sm">
                <span className="font-medium">{String(record.title)}</span>
                {record.description && (
                    <span className="ml-1">{String(record.description)}</span>
                )}
            </p>
        );
    }

    // Fallback: show key count
    const keys = Object.keys(record);
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
