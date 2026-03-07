// Copyright (c) 2025 Bytedance Ltd. and/or its affiliates
// SPDX-License-Identifier: MIT

import { Check, Copy } from "lucide-react";
import { useMemo, useState } from "react";
import ReactMarkdown, {
  type Options as ReactMarkdownOptions,
} from "react-markdown";
import rehypeKatex from "rehype-katex";
import remarkGfm from "remark-gfm";
import remarkMath from "remark-math";
import "katex/dist/katex.min.css";

import { Button } from "../ui/button";
import { useTranslations } from "../../lib/deep-research/i18n";
import { rehypeSplitWordsIntoSpans } from "../../lib/deep-research/rehype";
import { katexOptions } from "../../lib/deep-research/markdown/katex";
import { autoFixMarkdown, linkifyBareInlineCitations, normalizeMathForDisplay } from "../../lib/deep-research/utils/markdown";
import { cn } from "../../lib/utils";

import InlineCitation from "../chat/InlineCitation";
import Image from "./image";
import { Tooltip } from "./tooltip";
import { Link } from "./link";
import { CitationLink } from "./citation";
import type { Citation } from "../../lib/deep-research/messages";

function extractNodeText(node: React.ReactNode): string {
  if (typeof node === "string" || typeof node === "number") {
    return String(node);
  }
  if (Array.isArray(node)) {
    return node.map(extractNodeText).join("");
  }
  if (node && typeof node === "object" && "props" in node) {
    return extractNodeText((node as { props?: { children?: React.ReactNode } }).props?.children);
  }
  return "";
}

function parseInlineCitationText(text: string): { index: number; pageInfo?: string } | null {
  const normalizedText = text.replace(/\u200b/g, "").trim();
  const pageInfoMatch = normalizedText.match(/p\.?\s*([0-9,\-\s]+)/i);
  const pageInfo = pageInfoMatch ? `p.${pageInfoMatch[1].trim()}` : undefined;

  const indexMatch =
    normalizedText.match(/^\[\[(\d+)(?:\s*,\s*p\.?[^\]]+)?\]\]$/) ??
    normalizedText.match(/^\[(\d+)(?:\s*,\s*p\.?[^\]]+)?\]$/) ??
    normalizedText.match(/^\^?(\d+)\^?$/);

  if (!indexMatch) {
    return null;
  }

  return {
    index: Number(indexMatch[1]),
    pageInfo,
  };
}

function normalizeTreeLikeText(text: string): string {
  return text
    .replace(/\u00a0/g, " ")
    .replace(/[ \t]+\n/g, "\n")
    .trim();
}

function isTreeLikeParagraph(text: string): boolean {
  const normalized = normalizeTreeLikeText(text);
  if (!normalized) return false;

  const lines = normalized.split(/\n/).filter((line) => line.trim().length > 0);
  if (lines.length < 2) return false;

  const markerLines = lines.filter((line) => /[│├└┌┐┬┴─→]|(?:^|\s)[|｜](?:\s|$)/.test(line));
  return markerLines.length >= 2;
}

export function Markdown({
  className,
  children,
  style,
  components: customComponents,
  enableCopy,
  animated = false,
  checkLinkCredibility = false,
  citations = [],
  ...props
}: ReactMarkdownOptions & {
  className?: string;
  enableCopy?: boolean;
  style?: React.CSSProperties;
  animated?: boolean;
  checkLinkCredibility?: boolean;
  citations?: Citation[];
}) {
  const citationNumberMap = useMemo(() => {
    const map = new Map<number, Citation>();
    citations?.forEach((citation, index) => {
      const citationNumber = typeof (citation as Citation & { number?: unknown }).number === "number"
        ? (citation as Citation & { number: number }).number
        : index + 1;
      if (!map.has(citationNumber)) {
        map.set(citationNumber, citation);
      }
    });
    return map;
  }, [citations]);

  // Pre-compute normalized URL map for O(1) lookup
  const citationMap = useMemo(() => {
    const map = new Map<string, number>();
    citations?.forEach((c, index) => {
      if (!c.url) return;

      // Add exact match
      map.set(c.url, index);

      // Add decoded match
      try {
        const decoded = decodeURIComponent(c.url);
        if (decoded !== c.url) map.set(decoded, index);
      } catch { }

      // Add encoded match
      try {
        const encoded = encodeURI(c.url);
        if (encoded !== c.url) map.set(encoded, index);
      } catch { }
    });
    return map;
  }, [citations]);

  const components: ReactMarkdownOptions["components"] = useMemo(() => {
    return {
      a: ({ href, children }) => {
        const hrefStr = href ?? "";
        const childrenText = extractNodeText(children);
        const inlineCitation = parseInlineCitationText(childrenText);

        // Handle citation anchor targets (rendered in Reference list)
        // Format: [[n]](#citation-target-n)
        const targetMatch = hrefStr.match(/^#citation-target-(\d+)$/);
        if (targetMatch) {
          const index = targetMatch[1];
          return (
            <span
              id={`ref-${index}`}
              style={{
                fontWeight: 700,
                color: "#667eea",
                scrollMarginTop: "5rem",
              }}
            >
              [{index}]
            </span>
          );
        }

        // Handle inline citation links (rendered in text)
        // Format: [[n]](#cite-n), [[n]](#ref-n), [n](#ref1), [n](#1)
        const linkMatch = hrefStr.match(/^#(?:cite-|ref-?)?(\d+)$/);
        if (linkMatch) {
          const index = Number(linkMatch[1]);
          const citation = citationNumberMap.get(index) ?? citations[index - 1];

          return (
            <InlineCitation
              index={index}
              title={citation?.title}
              source={citation?.domain}
              snippet={citation?.content_snippet ?? citation?.description}
              pageInfo={inlineCitation?.pageInfo}
              url={citation?.url}
            />
          );
        }

        if (inlineCitation && citations.length > 0) {
          const matchedCitationIndex = citationMap.get(hrefStr);
          const numberedCitation = citationNumberMap.get(inlineCitation.index);
          const fallbackCitationIndex = inlineCitation.index - 1;
          const resolvedCitationIndex = matchedCitationIndex ?? fallbackCitationIndex;
          const citation = numberedCitation ?? citations[resolvedCitationIndex];

          if (citation || (inlineCitation.index >= 1 && inlineCitation.index <= citations.length)) {
            return (
              <InlineCitation
                index={inlineCitation.index}
                title={citation?.title}
                source={citation?.domain}
                snippet={citation?.content_snippet ?? citation?.description}
                pageInfo={inlineCitation.pageInfo}
                url={citation?.url ?? hrefStr}
              />
            );
          }
        }

        // If we have citation data, use CitationLink for enhanced display
        if (citations && citations.length > 0) {
          // Find if this URL is one of our citations
          const citationIndex = citationMap.get(hrefStr) ?? -1;

          if (citationIndex !== -1) {
            // Heuristic to determine if this is a citation target (in Reference list)
            // vs a citation link (in text).
            // Targets are usually the full title, while links are numbers like [1].
            // Heuristic: inline citation text usually looks like a numeric marker
            // rather than a full title. We treat the following as "inline":
            //   "1", "[1]", "^1^", "[^1]" (with optional surrounding whitespace).
            // This pattern matches either:
            //   - a bracketed number: "[1]"
            //   - a caret-style number: "1", "^1", "1^", "^1^"
            // and ignores surrounding whitespace.
            const isInline = inlineCitation != null;

            return (
              <CitationLink
                href={hrefStr}
                citations={citations}
                id={!isInline ? `ref-${citationIndex + 1}` : undefined}
              >
                {children}
              </CitationLink>
            );
          }

          return (
            <CitationLink href={hrefStr} citations={citations}>
              {children}
            </CitationLink>
          );
        }
        // Otherwise fall back to regular Link
        const isExternal = href?.startsWith("http");
        return (
          <Link href={href} checkLinkCredibility={checkLinkCredibility}>
            {children}
            {isExternal && <span className="inline-block ml-0.5 opacity-70 text-[0.7em] no-underline">↗</span>}
          </Link>
        );
      },
      img: ({ src, alt }) => (
        <a href={src as string} target="_blank" rel="noopener noreferrer">
          <Image className="rounded" src={src as string} alt={alt ?? ""} />
        </a>
      ),
      hr: () => (
        <div className="my-6 flex items-center gap-3">
          <div className="flex-1 h-px bg-gradient-to-r from-transparent via-gray-200 to-transparent" />
          <div className="w-1 h-1 rounded-full bg-gray-300" />
          <div className="flex-1 h-px bg-gradient-to-r from-transparent via-gray-200 to-transparent" />
        </div>
      ),
      table: ({ children }) => (
        <div className="overflow-x-auto my-3 rounded-lg border border-gray-200 shadow-sm">
          <table className="min-w-full">{children}</table>
        </div>
      ),
      p: ({ children }) => {
        const text = extractNodeText(children);
        if (isTreeLikeParagraph(text)) {
          return (
            <div className="my-4 overflow-x-auto rounded-2xl border border-slate-200 bg-gradient-to-br from-slate-50 to-white px-4 py-3 shadow-sm">
              <pre className="m-0 whitespace-pre font-mono text-[13px] leading-6 text-slate-700">
                {normalizeTreeLikeText(text)}
              </pre>
            </div>
          );
        }

        return <p>{children}</p>;
      },
      ...(customComponents || {}),
    };
  }, [checkLinkCredibility, citations, citationMap, citationNumberMap, customComponents]);

  const displayMarkdown = useMemo(() => {
    const normalizedMarkdown = dropMarkdownQuote(normalizeMathForDisplay(children ?? "")) ?? "";
    const linkifiedMarkdown = citations.length > 0
      ? linkifyBareInlineCitations(normalizedMarkdown)
      : normalizedMarkdown;
    return autoFixMarkdown(linkifiedMarkdown);
  }, [children, citations]);

  const rehypePlugins = useMemo<NonNullable<ReactMarkdownOptions["rehypePlugins"]>>(() => {
    const plugins: NonNullable<ReactMarkdownOptions["rehypePlugins"]> = [[
      rehypeKatex,
      katexOptions,
    ]];
    if (animated) {
      plugins.push(rehypeSplitWordsIntoSpans);
    }
    return plugins;
  }, [animated]);
  return (
    <div className={cn(className, "prose dark:prose-invert")} style={style}>
      <ReactMarkdown
        remarkPlugins={[remarkGfm, remarkMath]}
        rehypePlugins={rehypePlugins}
        components={components}
        {...props}
      >
        {displayMarkdown}
      </ReactMarkdown>
      {enableCopy && typeof children === "string" && (
        <div className="flex">
          <CopyButton content={children} />
        </div>
      )}
    </div>
  );
}

function CopyButton({ content }: { content: string }) {
  // @ts-ignore - i18n shim
  const t = useTranslations("chat.research");
  const [copied, setCopied] = useState(false);
  return (
    <Tooltip title={t("copy")}>
      <Button
        variant="outline"
        size="sm"
        className="rounded-full"
        onClick={async () => {
          try {
            await navigator.clipboard.writeText(content);
            setCopied(true);
            setTimeout(() => {
              setCopied(false);
            }, 1000);
          } catch (error) {
            console.error(error);
          }
        }}
      >
        {copied ? (
          <Check className="h-4 w-4" />
        ) : (
          <Copy className="h-4 w-4" />
        )}{" "}
      </Button>
    </Tooltip>
  );
}



function dropMarkdownQuote(markdown?: string | null): string | null {
  if (!markdown) return null;

  const patternsToRemove = [
    { prefix: "```markdown\n", suffix: "\n```", prefixLen: 12 },
    { prefix: "```text\n", suffix: "\n```", prefixLen: 8 },
    { prefix: "```\n", suffix: "\n```", prefixLen: 4 },
  ];

  let result = markdown;

  for (const { prefix, suffix, prefixLen } of patternsToRemove) {
    if (result.startsWith(prefix) && !result.endsWith(suffix)) {
      result = result.slice(prefixLen);
      break;  // remove prefix without suffix only once
    }
  }

  let changed = true;

  while (changed) {
    changed = false;

    for (const { prefix, suffix, prefixLen } of patternsToRemove) {
      let startIndex = 0;
      while ((startIndex = result.indexOf(prefix, startIndex)) !== -1) {
        const endIndex = result.indexOf(suffix, startIndex + prefixLen);
        if (endIndex !== -1) {
          // only remove fully matched code blocks
          const before = result.slice(0, startIndex);
          const content = result.slice(startIndex + prefixLen, endIndex);
          const after = result.slice(endIndex + suffix.length);
          result = before + content + after;
          changed = true;
          startIndex = before.length + content.length;
        } else {
          startIndex += prefixLen;
        }
      }
    }
  }

  return result;
}