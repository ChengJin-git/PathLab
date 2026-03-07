import React, { useMemo, useRef } from "react";
import { CitationList } from "../../../../components/deep-research/citation";
import { cn } from "../../../../lib/utils";
import { Markdown } from "../../../../components/deep-research/markdown";
import { stripResearchMeta } from "../../../../lib/deep-research/utils";
import { stripMarkdownReferenceSection } from "../../../../lib/deep-research/utils/markdown";
import type { Citation } from "../../../../lib/deep-research/messages";

function generateSlug(text: string): string {
    return text
        .toLowerCase()
        .replace(/\s+/g, "-")
        .replace(/[^\w\-]+/g, "")
        .replace(/\-\-+/g, "-")
        .replace(/^-+/, "")
        .replace(/-+$/, "");
}

function extractHeadings(markdown: string): { id: string; level: number }[] {
    const headings: { id: string; level: number }[] = [];
    const lines = markdown.split("\n");
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
                const text = match[2].replace(/[*_~`]/g, "").trim();
                headings.push({ id: generateSlug(text), level });
            }
        }
    }

    // Deduplicate IDs
    const idCounts = new Map<string, number>();
    return headings.map((h) => {
        let finalId = h.id;
        const count = idCounts.get(finalId) || 0;
        if (count > 0) finalId = `${finalId}-${count}`;
        idCounts.set(h.id, count + 1);
        return { ...h, id: finalId };
    });
}

export function ReportLayout({
    content = "",
    citations,
    className,
}: {
    content?: string;
    citations?: Citation[];
    className?: string;
}) {
    const cleanContent = useMemo(() => stripResearchMeta(content), [content]);
    const bodyContent = useMemo(
        () => stripMarkdownReferenceSection(cleanContent),
        [cleanContent],
    );
    const headings = useMemo(() => extractHeadings(bodyContent), [bodyContent]);

    // Heading counter consumed sequentially by react-markdown as it renders h1-h4.
    // Uses the pre-computed headings array so IDs stay stable.
    const headingCursor = useRef(0);

    const headingComponents = useMemo(() => {
        headingCursor.current = 0;

        const nextId = () => {
            const idx = headingCursor.current;
            headingCursor.current += 1;
            return headings[idx]?.id ?? `heading-${idx}`;
        };

        return {
            h1: ({ children, node, ...props }: any) => (
                <h1 {...props} id={nextId()} className="mb-6 text-2xl leading-tight font-semibold text-gray-950 scroll-mt-20 sm:mb-8 sm:text-4xl break-words whitespace-normal">{children}</h1>
            ),
            h2: ({ children, node, ...props }: any) => (
                <h2 {...props} id={nextId()} className="mt-8 mb-4 border-b border-gray-900/20 pb-2.5 text-xl font-semibold text-gray-950 scroll-mt-20 sm:mt-12 sm:mb-5 sm:pb-3 sm:text-3xl break-words whitespace-normal">{children}</h2>
            ),
            h3: ({ children, node, ...props }: any) => (
                <h3 {...props} id={nextId()} className="mt-6 mb-2.5 text-lg font-semibold text-gray-900 scroll-mt-20 sm:mt-8 sm:mb-3 sm:text-2xl break-words whitespace-normal">{children}</h3>
            ),
            h4: ({ children, node, ...props }: any) => (
                <h4 {...props} id={nextId()} className="scroll-mt-20 mt-6 mb-2 text-base font-semibold text-gray-900 break-words whitespace-normal">{children}</h4>
            ),
        };
    }, [headings]);

    return (
        <div className={cn("relative w-full min-w-0 max-w-full", className)}>
            <div className="report-content w-full min-w-0 max-w-full overflow-x-hidden break-words [&_table]:block [&_table]:w-full [&_table]:overflow-x-auto" style={{ overflowWrap: "anywhere", wordBreak: "break-word" }}>
                <Markdown
                    className="prose-sm sm:prose-base prose-slate min-w-0 max-w-none
                        prose-p:my-3 prose-p:leading-7 prose-p:text-gray-700 sm:prose-p:leading-8
                        prose-headings:text-gray-950
                        prose-strong:font-semibold prose-strong:text-gray-950
                        prose-ul:my-4 prose-ul:list-disc prose-ul:pl-5 sm:prose-ul:pl-6
                        prose-ol:my-4 prose-ol:list-decimal prose-ol:pl-5 sm:prose-ol:pl-6
                        prose-li:my-2 prose-li:leading-7 prose-li:text-gray-700
                        prose-code:rounded prose-code:bg-gray-100 prose-code:px-1.5 prose-code:py-0.5 prose-code:text-[0.9em] prose-code:text-gray-800 prose-code:before:content-none prose-code:after:content-none
                        prose-pre:my-5 prose-pre:rounded-xl prose-pre:bg-gray-900 prose-pre:p-3 sm:prose-pre:p-4 prose-pre:text-gray-100
                        prose-a:no-underline prose-hr:my-6 prose-blockquote:border-gray-300 prose-blockquote:text-gray-700"
                    animated
                    checkLinkCredibility={false}
                    citations={citations}
                    components={headingComponents}
                >
                    {bodyContent}
                </Markdown>
            </div>
            {citations && citations.length > 0 && (
                <CitationList className="mt-6" citations={citations} />
            )}
        </div>
    );
}
