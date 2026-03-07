import React, { useMemo, useRef } from "react";
import { cn } from "../../../../lib/utils";
import { Markdown } from "../../../../components/deep-research/markdown";
import { stripResearchMeta } from "../../../../lib/deep-research/utils";
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
            h1: ({ children, node, ...props }: any) => (
                <h1 {...props} id={nextId()} className="scroll-mt-20 group relative text-3xl font-bold leading-tight mb-6">{children}</h1>
            ),
            h2: ({ children, node, ...props }: any) => (
                <h2 {...props} id={nextId()} className="scroll-mt-20 group relative text-2xl font-semibold border-b pb-2 mt-10 mb-5">{children}</h2>
            ),
            h3: ({ children, node, ...props }: any) => (
                <h3 {...props} id={nextId()} className="scroll-mt-20 group relative text-xl font-semibold mt-8 mb-4">{children}</h3>
            ),
            h4: ({ children, node, ...props }: any) => (
                <h4 {...props} id={nextId()} className="scroll-mt-20 group relative text-lg font-medium mt-6 mb-3">{children}</h4>
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
