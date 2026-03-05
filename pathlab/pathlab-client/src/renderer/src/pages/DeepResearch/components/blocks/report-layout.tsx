import React, { useMemo, useRef } from "react";
import { cn } from "../../../../lib/utils";
import { Markdown } from "../../../../components/deep-research/markdown";
import type { CitationData } from "../../../../components/deep-research/citation";

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

/** Strip PATHLAB_RESEARCH_META blocks so they don't leak into rendered output. */
function stripMetaBlocks(md: string): string {
    return md.replace(/\[PATHLAB_RESEARCH_META\][\s\S]*?(?:\[\/PATHLAB_RESEARCH_META\]|$)/g, "").trim();
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
    const cleanContent = useMemo(() => stripMetaBlocks(content), [content]);
    const headings = useMemo(() => extractHeadings(cleanContent), [cleanContent]);

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
            h1: ({ children, ...props }: any) => (
                <h1 id={nextId()} className="scroll-mt-20 group relative" {...props}>{children}</h1>
            ),
            h2: ({ children, ...props }: any) => (
                <h2 id={nextId()} className="scroll-mt-20 group relative border-b pb-2 mt-10 mb-5" {...props}>{children}</h2>
            ),
            h3: ({ children, ...props }: any) => (
                <h3 id={nextId()} className="scroll-mt-20 group relative mt-8 mb-4" {...props}>{children}</h3>
            ),
            h4: ({ children, ...props }: any) => (
                <h4 id={nextId()} className="scroll-mt-20 group relative mt-6 mb-3" {...props}>{children}</h4>
            ),
        };
    }, [headings]);

    return (
        <div className={cn("relative w-full", className)}>
            <div className="report-content w-full break-words [&_table]:w-full [&_table]:overflow-x-auto [&_table]:block" style={{ overflowWrap: "anywhere", wordBreak: "break-word" }}>
                <Markdown
                    className="max-w-none"
                    animated
                    checkLinkCredibility
                    citations={citations}
                    components={headingComponents}
                >
                    {cleanContent}
                </Markdown>
            </div>
        </div>
    );
}
