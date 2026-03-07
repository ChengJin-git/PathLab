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

const __pageCache = new LRUCache<string, string>({ max: 100 });
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
    return (
        <section className="mt-4 pl-4">
            <div className="font-medium italic">
                <RainbowText
                    className="flex items-center"
                    animated={searchResults === undefined}
                >
                    <Search size={16} className={"mr-2"} />
                    <span>{t("searchingFor")}&nbsp;</span>
                    <span className="max-w-[500px] overflow-hidden text-ellipsis whitespace-nowrap">
                        {(toolCall.args as { query: string }).query}
                    </span>
                </RainbowText>
            </div>
            <div className="pr-4">
                {pageResults && (
                    <ul className="mt-2 flex flex-wrap gap-4">
                        {searching &&
                            [...Array(6)].map((_, i) => (
                                <li
                                    key={`search-result-${i}`}
                                    className="flex h-40 w-40 gap-2 rounded-md text-sm"
                                >
                                    <Skeleton
                                        className="to-accent h-full w-full rounded-md bg-gradient-to-tl from-slate-400"
                                        style={{ animationDelay: `${i * 0.2}s` }}
                                    />
                                </li>
                            ))}
                        {pageResults
                            .filter((result) => result.type === "page")
                            .slice(0, 20) // Limit displayed results for performance
                            .map((searchResult, i) => {
                                const shouldAnimate = i < 6; // Only animate first 6 results
                                return (
                                    <motion.li
                                        key={`search-result-${i}`}
                                        className="text-muted-foreground bg-accent flex max-w-40 gap-2 rounded-md px-2 py-1 text-sm"
                                        initial={shouldAnimate ? { opacity: 0, y: 10 } : { opacity: 1, y: 0 }}
                                        animate={{ opacity: 1, y: 0 }}
                                        transition={shouldAnimate ? {
                                            duration: 0.15, // Reduced from 0.2
                                            delay: Math.min(i * 0.05, 0.3), // Cap delay at 0.3s
                                            ease: "easeOut",
                                        } : undefined}
                                    >
                                        <FavIcon
                                            className="mt-1"
                                            url={searchResult.url}
                                            title={searchResult.title}
                                        />
                                        <a href={searchResult.url} target="_blank">
                                            {searchResult.title}
                                        </a>
                                    </motion.li>
                                );
                            })}
                        {imageResults
                            .slice(0, 10) // Limit displayed images for performance
                            .map((searchResult, i) => {
                                const shouldAnimate = i < 4; // Only animate first 4 images
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
                                        <a
                                            className="flex flex-col gap-2 overflow-hidden rounded-md opacity-75 transition-opacity duration-300 hover:opacity-100"
                                            href={searchResult.image_url}
                                            target="_blank"
                                        >
                                            <Image
                                                src={searchResult.image_url}
                                                alt={searchResult.image_description}
                                                className="bg-accent h-40 w-40 max-w-full rounded-md bg-cover bg-center bg-no-repeat"
                                                imageClassName="hover:scale-110"
                                                imageTransition
                                            />
                                        </a>
                                    </motion.li>
                                );
                            })}
                    </ul>
                )}
            </div>
        </section>
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
        <section className="mt-4 pl-4">
            <div>
                <RainbowText
                    className="flex items-center text-base font-medium italic"
                    animated={toolCall.result === undefined}
                >
                    <BookOpenText size={16} className={"mr-2"} />
                    <span>{t("reading")}</span>
                </RainbowText>
            </div>
            <ul className="mt-2 flex flex-wrap gap-4">
                <motion.li
                    className="text-muted-foreground bg-accent flex h-40 w-40 gap-2 rounded-md px-2 py-1 text-sm"
                    initial={{ opacity: 0, y: 10 }}
                    animate={{ opacity: 1, y: 0 }}
                    transition={{
                        duration: 0.15, // Reduced for better performance
                        ease: "easeOut",
                    }}
                >
                    <FavIcon className="mt-1" url={url} title={title} />
                    <a
                        className="h-full flex-grow overflow-hidden text-ellipsis whitespace-nowrap"
                        href={url}
                        target="_blank"
                    >
                        {title ?? url}
                    </a>
                </motion.li>
            </ul>
        </section>
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
    return (
        <section className="mt-4 pl-4">
            <div className="font-medium italic">
                <RainbowText className="flex items-center" animated={searching}>
                    <Search size={16} className={"mr-2"} />
                    <span>{t("retrievingDocuments")}&nbsp;</span>
                    <span className="max-w-[500px] overflow-hidden text-ellipsis whitespace-nowrap">
                        {(toolCall.args as { keywords: string }).keywords}
                    </span>
                </RainbowText>
            </div>
            <div className="pr-4">
                {documents && (
                    <ul className="mt-2 flex flex-wrap gap-4">
                        {searching &&
                            [...Array(2)].map((_, i) => (
                                <li
                                    key={`search-result-${i}`}
                                    className="flex h-40 w-40 gap-2 rounded-md text-sm"
                                >
                                    <Skeleton
                                        className="to-accent h-full w-full rounded-md bg-gradient-to-tl from-slate-400"
                                        style={{ animationDelay: `${i * 0.2}s` }}
                                    />
                                </li>
                            ))}
                        {documents?.map((doc, i) => {
                            const shouldAnimate = i < 4; // Only animate first 4 documents
                            return (
                                <motion.li
                                    key={`search-result-${i}`}
                                    className="text-muted-foreground bg-accent flex max-w-40 gap-2 rounded-md px-2 py-1 text-sm"
                                    initial={shouldAnimate ? { opacity: 0, y: 10 } : { opacity: 1, y: 0 }}
                                    animate={{ opacity: 1, y: 0 }}
                                    transition={shouldAnimate ? {
                                        duration: 0.15,
                                        delay: Math.min(i * 0.05, 0.2),
                                        ease: "easeOut",
                                    } : undefined}
                                >
                                    <FileText size={32} />
                                    {doc.title} (chunk-{i},size-{doc.content.length})
                                </motion.li>
                            );
                        })}
                    </ul>
                )}
            </div>
        </section>
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
        <section className="mt-4 pl-4">
            <div className="flex items-center">
                <PythonOutlined className={"mr-2"} />
                <RainbowText
                    className="text-base font-medium italic"
                    animated={toolCall.result === undefined}
                >
                    {t("runningPythonCode")}
                </RainbowText>
            </div>
            <div>
                <div className="bg-accent mt-2 max-h-[400px] max-w-[calc(100%-120px)] overflow-y-auto rounded-md p-2 text-sm">
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
            </div>
            {toolCall.result && <PythonToolCallResult result={toolCall.result} />}
        </section>
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
            <div className="mt-4 font-medium italic">
                {hasError ? t("errorExecutingCode") : t("executionOutput")}
            </div>
            <div className="bg-accent mt-2 max-h-[400px] max-w-[calc(100%-120px)] overflow-y-auto rounded-md p-2 text-sm">
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
                    {error ?? stdout ?? "(empty)"}
                </SyntaxHighlighter>
            </div>
        </>
    );
}

// Friendly display names and icons for known tool functions
export const TOOL_DISPLAY_MAP: Record<
    string,
    { label: string; icon: React.ReactNode; description: string }
> = {
    validate_url: {
        label: "Verifying source authenticity",
        icon: <ShieldCheck size={16} className="mr-2 text-blue-500" />,
        description: "Checking if the web page is accessible and trustworthy",
    },
    crawl_tool: {
        label: "Reading web page",
        icon: <Globe size={16} className="mr-2 text-green-500" />,
        description: "Extracting content from the web page",
    },
    web_search: {
        label: "Searching the web",
        icon: <Search size={16} className="mr-2 text-purple-500" />,
        description: "Performing a web search query",
    },
    python_repl_tool: {
        label: "Running code analysis",
        icon: <Wrench size={16} className="mr-2 text-orange-500" />,
        description: "Executing Python code for data analysis",
    },
};

export function getToolDisplay(toolName: string) {
    if (TOOL_DISPLAY_MAP[toolName]) {
        return TOOL_DISPLAY_MAP[toolName];
    }
    // Generate a friendly name from snake_case function name
    const friendlyName = toolName
        .replace(/_/g, " ")
        .replace(/\b\w/g, (c) => c.toUpperCase());
    return {
        label: friendlyName,
        icon: <PencilRuler size={16} className="mr-2 text-gray-500" />,
        description: `Running tool: ${toolName}`,
    };
}

/** Try to render a user-friendly summary from tool call result JSON */
export function MCPToolResultSummary({ result }: { result: string }) {
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
                    {isValid ? "Source verified" : "Source unavailable"}
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
            Returned {keys.length} field{keys.length !== 1 ? "s" : ""}: {keys.slice(0, 5).join(", ")}
            {keys.length > 5 ? "…" : ""}
        </p>
    );
}

export function MCPToolCall({ toolCall }: { toolCall: ToolCallRuntime }) {
    const tool = useMemo(() => findMCPTool(toolCall.name), [toolCall.name]);
    const display = useMemo(() => getToolDisplay(toolCall.name), [toolCall.name]);
    const { resolvedTheme } = useTheme();
    const isRunning = toolCall.result === undefined;

    return (
        <section className="mt-4 pl-4">
            <div className="w-fit overflow-y-auto rounded-md py-0">
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
                                            Show raw data
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
