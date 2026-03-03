import { motion } from "framer-motion";
import React, { useEffect, useMemo, useRef, useState } from "react";
import { CopyButton } from "../../../../components/deep-research/markdown";
import { cn } from "../../../../lib/utils";
import { Markdown } from "../../../../components/deep-research/markdown";
import type { CitationData } from "../../../../components/deep-research/citation";

interface HeadingItem {
    id: string;
    text: string;
    level: number;
}

function generateSlug(text: string): string {
    // Simple slugifier that matches rehype-slug output style
    return text
        .toLowerCase()
        .replace(/\s+/g, "-")
        .replace(/[^\w\-]+/g, "")
        .replace(/\-\-+/g, "-")
        .replace(/^-+/, "")
        .replace(/-+$/, "");
}

// Function to parse markdown and extract headings
function extractHeadings(markdown: string): HeadingItem[] {
    const headings: HeadingItem[] = [];
    const lines = markdown.split("\n");

    // Exclude code blocks when extracting
    let inCodeBlock = false;

    for (const line of lines) {
        if (line.trim().startsWith("```")) {
            inCodeBlock = !inCodeBlock;
            continue;
        }

        if (!inCodeBlock) {
            const match = line.match(/^(#{1,4})\s+(.+)$/);
            if (match) {
                const level = match[1].length;
                const rawText = match[2];
                const text = rawText.replace(/[*_~`]/g, "").trim(); // Remove basic markdown formatting for TOC display
                headings.push({
                    id: generateSlug(text),
                    text,
                    level,
                });
            }
        }
    }

    // Deduplicate IDs if they happen to be identical
    const idCounts = new Map<string, number>();
    return headings.map((heading) => {
        let finalId = heading.id;
        const count = idCounts.get(finalId) || 0;
        if (count > 0) {
            finalId = `${finalId}-${count}`;
        }
        idCounts.set(heading.id, count + 1);
        return { ...heading, id: finalId };
    });
}

export function ReportLayout({
    content = "",
    citations,
    className,
}: {
    content?: string;
    citations?: CitationData[];
    className?: string;
}) {
    const headings = useMemo(() => extractHeadings(content), [content]);
    const [activeId, setActiveId] = useState<string>("");
    const [readingProgress, setReadingProgress] = useState(0);

    // Set up intersection observer for scroll spy
    useEffect(() => {
        if (headings.length === 0) return;

        // Track scroll progress
        const handleScroll = () => {
            // Find active header
            const headingElements = headings
                .map((h) => document.getElementById(h.id))
                .filter((el): el is HTMLElement => el !== null);

            if (headingElements.length === 0) return;

            // Calculate progress
            const scrollPosition = window.scrollY;
            const docHeight = document.documentElement.scrollHeight - window.innerHeight;
            const scrollPercentage = docHeight > 0 ? (scrollPosition / docHeight) * 100 : 0;
            setReadingProgress(Math.min(100, Math.max(0, scrollPercentage)));

            // Find the currently active heading
            // A heading is considered "active" if it's past the top of the viewport (with an offset)
            // but hasn't been completely pushed out by the next heading.
            const viewportTop = window.scrollY + 100; // 100px offset for sticky headers/padding

            let currentActiveId = headingElements[0].id;
            for (const element of headingElements) {
                if (element.offsetTop <= viewportTop) {
                    currentActiveId = element.id;
                } else {
                    break;
                }
            }

            setActiveId(currentActiveId);
        };

        window.addEventListener("scroll", handleScroll, { passive: true });
        // Run once on mount
        handleScroll();

        return () => window.removeEventListener("scroll", handleScroll);
    }, [headings]);

    // ID tracker for heading renderer to mirror deduplication
    const idCounts = useRef(new Map<string, number>());

    // Custom header components for ReactMarkdown to inject IDs
    const headingComponents = useMemo(() => {
        idCounts.current.clear(); // Reset on re-render

        const getId = (children: any) => {
            const text = String(children);
            let id = generateSlug(text);
            const count = idCounts.current.get(id) || 0;
            if (count > 0) {
                id = `${id}-${count}`;
            }
            idCounts.current.set(generateSlug(text), count + 1);
            return id;
        };

        return {
            h1: ({ children, ...props }: any) => {
                const id = getId(children);
                return <h1 id={id} className="scroll-mt-20 group relative" {...props}>
                    {children}
                </h1>;
            },
            h2: ({ children, ...props }: any) => {
                const id = getId(children);
                return <h2 id={id} className="scroll-mt-20 group relative border-b pb-2 mt-10 mb-5" {...props}>
                    {children}
                </h2>;
            },
            h3: ({ children, ...props }: any) => {
                const id = getId(children);
                return <h3 id={id} className="scroll-mt-20 group relative mt-8 mb-4" {...props}>
                    {children}
                </h3>;
            },
            h4: ({ children, ...props }: any) => {
                const id = getId(children);
                return <h4 id={id} className="scroll-mt-20 group relative mt-6 mb-3" {...props}>
                    {children}
                </h4>;
            }
        };
    }, [content]);

    const scrollToHeading = (id: string, e: React.MouseEvent) => {
        e.preventDefault();
        const element = document.getElementById(id);
        if (element) {
            // 80 is the offset for sticky headers
            const y = element.getBoundingClientRect().top + window.scrollY - 80;
            window.scrollTo({ top: y, behavior: "smooth" });
        }
    };

    return (
        <div className={cn("relative flex w-full max-w-7xl mx-auto flex-col lg:flex-row gap-8 items-start", className)}>
            {/* Reading Progress Indicator (Top) - visible mainly on mobile */}
            <div className="fixed top-0 left-0 right-0 h-1 z-50 bg-secondary/50 lg:hidden">
                <motion.div
                    className="h-full bg-primary"
                    style={{ width: `${readingProgress}%` }}
                />
            </div>

            {/* Left Sidebar Table of Contents for Desktop */}
            {headings.length > 0 && (
                <div className="hidden lg:block w-64 shrink-0 sticky top-24 self-start max-h-[calc(100vh-8rem)] overflow-y-auto custom-scrollbar pb-10">
                    <div className="mb-4 text-sm font-semibold text-muted-foreground uppercase tracking-wider">
                        Table of Contents
                    </div>
                    <div className="flex bg-secondary/50 h-1 mb-4 rounded-full overflow-hidden">
                        <motion.div
                            className="bg-primary h-full"
                            style={{ width: `${readingProgress}%` }}
                        />
                    </div>
                    <nav className="flex flex-col gap-1 text-sm">
                        {headings.map((heading) => {
                            const isActive = activeId === heading.id;
                            return (
                                <a
                                    key={heading.id}
                                    href={`#${heading.id}`}
                                    onClick={(e) => scrollToHeading(heading.id, e)}
                                    className={cn(
                                        "block py-1 pr-2 transition-colors duration-200 break-words",
                                        heading.level === 1 ? "pl-0 font-medium" :
                                            heading.level === 2 ? "pl-3" :
                                                heading.level === 3 ? "pl-6 text-xs" : "pl-9 text-xs",
                                        isActive
                                            ? "text-primary font-medium"
                                            : "text-muted-foreground hover:text-foreground"
                                    )}
                                    style={{
                                        borderLeft: isActive ? "2px solid hsl(var(--primary))" : "2px solid transparent",
                                        marginLeft: heading.level === 1 ? 0 : "-2px"
                                    }}
                                >
                                    {heading.text}
                                </a>
                            );
                        })}
                    </nav>
                </div>
            )}

            {/* Main Content Area */}
            <div className="flex-1 w-full min-w-0">
                {/* Mobile TOC Accordion */}
                {headings.length > 0 && (
                    <details className="lg:hidden mb-8 border rounded-lg bg-card text-card-foreground shadow-sm">
                        <summary className="p-4 font-semibold cursor-pointer select-none">
                            Table of Contents
                        </summary>
                        <nav className="p-4 pt-0 flex flex-col gap-2 text-sm border-t mt-2">
                            {headings.map((heading) => (
                                <a
                                    key={heading.id}
                                    href={`#${heading.id}`}
                                    onClick={(e) => {
                                        scrollToHeading(heading.id, e);
                                        // Close details on mobile after click
                                        const details = e.currentTarget.closest('details');
                                        if (details) details.removeAttribute('open');
                                    }}
                                    className={cn(
                                        "block py-1",
                                        heading.level === 1 ? "pl-0" :
                                            heading.level === 2 ? "pl-4 text-muted-foreground" :
                                                heading.level === 3 ? "pl-8 text-xs text-muted-foreground" : "pl-12 text-xs text-muted-foreground"
                                    )}
                                >
                                    {heading.text}
                                </a>
                            ))}
                        </nav>
                    </details>
                )}

                {/* The parsed Markdown report */}
                <div className="report-content w-full [&_table]:w-full [&_table]:overflow-x-auto [&_table]:block">
                    <Markdown
                        animated
                        checkLinkCredibility
                        citations={citations}
                        components={headingComponents}
                    >
                        {content}
                    </Markdown>
                </div>
            </div>
        </div>
    );
}
