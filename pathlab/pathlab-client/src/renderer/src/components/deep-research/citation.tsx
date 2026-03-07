// Copyright (c) 2025 Bytedance Ltd. and/or its affiliates
// SPDX-License-Identifier: MIT

import { ExternalLink, Globe, Clock, Star } from "lucide-react";
import { useMemo } from "react";

import {
  HoverCard,
  HoverCardContent,
  HoverCardTrigger,
} from "../ui/hover-card";
import { useTranslations } from "../../lib/deep-research/i18n";
import { cn } from "../../lib/utils";
import type { Citation } from "../../lib/deep-research/messages";

export const LINK_STYLE: React.CSSProperties = {
  color: "#667eea",
  textDecoration: "underline",
  textDecorationColor: "rgba(102, 126, 234, 0.3)",
  cursor: "pointer",
  transition: "background-color 0.15s, text-decoration-color 0.15s",
};

export const linkHoverHandlers = {
  onMouseEnter: (e: React.MouseEvent<HTMLElement>) => {
    e.currentTarget.style.backgroundColor = "rgba(102, 126, 234, 0.08)";
    e.currentTarget.style.textDecorationColor = "#667eea";
  },
  onMouseLeave: (e: React.MouseEvent<HTMLElement>) => {
    e.currentTarget.style.backgroundColor = "transparent";
    e.currentTarget.style.textDecorationColor = "rgba(102, 126, 234, 0.3)";
  },
};

interface CitationLinkProps {
  href: string;
  children: React.ReactNode;
  citations: Citation[];
  className?: string;
  id?: string;
}

/**
 * Enhanced link component that shows citation metadata on hover.
 * Used within markdown content to provide rich citation information.
 */
export function CitationLink({
  href,
  children,
  citations,
  className,
  id,
}: CitationLinkProps) {
  // Find matching citation data for this URL
  const { citation, index } = useMemo(() => {
    if (!href || !citations) return { citation: null, index: -1 };
    
    // Try exact match first
    let matchIndex = citations.findIndex((c) => c.url === href);
    
    // If not found, try versatile comparison using normalized URLs
    if (matchIndex === -1) {
      const normalizeUrl = (url: string) => {
        try {
          return decodeURIComponent(url).trim();
        } catch {
          return url.trim();
        }
      };

      const normalizedHref = normalizeUrl(href);
      
      matchIndex = citations.findIndex(
        (c) => normalizeUrl(c.url) === normalizedHref
      );
    }
    
    const match = matchIndex !== -1 ? citations[matchIndex] : null;
    
    return { citation: match, index: matchIndex };
  }, [href, citations]);

  const openInNewTab = (e: React.MouseEvent) => {
    if (!href) return;
    e.preventDefault();
    e.stopPropagation();
    window.open(href, "_blank", "noopener,noreferrer");
  };

  // If no citation data found, render as regular link
  if (!citation) {
    return (
      <a
        href={href}
        target="_blank"
        rel="noopener noreferrer"
        onClick={openInNewTab}
        style={LINK_STYLE}
        {...linkHoverHandlers}
        className={className}
      >
        {children}
      </a>
    );
  }

  // Determine if this is a reference list item (has id="ref-N") vs inline citation
  const isReferenceItem = !!id;

  const handleCitationClick = (e: React.MouseEvent) => {
    // Reference list items (id="ref-N") should always open in new tab
    if (isReferenceItem) {
      openInNewTab(e);
      return;
    }

    // Inline citations (e.g. [1]) scroll to the reference in the list
    if (index !== -1) {
      const targetId = `ref-${index + 1}`;
      const element = document.getElementById(targetId);
      if (element) {
        e.preventDefault();
        element.scrollIntoView({ behavior: "smooth", block: "start" });
        return;
      }
    }
    // Fallback: open in new tab
    openInNewTab(e);
  };

  return (
    <HoverCard openDelay={200} closeDelay={100}>
      <HoverCardTrigger asChild>
        <a
          id={id}
          href={href}
          target="_blank"
          rel="noopener noreferrer"
          onClick={handleCitationClick}
          style={{
            ...LINK_STYLE,
            display: "inline-flex",
            alignItems: "center",
            gap: "2px",
            scrollMarginTop: "5rem",
          }}
          {...linkHoverHandlers}
          className={className}
        >
          {children}
          <span className="text-xs text-muted-foreground ml-0.5">
            <ExternalLink className="h-3 w-3 inline" />
          </span>
        </a>
      </HoverCardTrigger>
      <HoverCardContent
        className="w-80 p-4"
        side="top"
        align="start"
        sideOffset={8}
      >
        <CitationCard citation={citation} />
      </HoverCardContent>
    </HoverCard>
  );
}

interface CitationCardProps {
  citation: Citation;
  compact?: boolean;
}

/**
 * Card component displaying citation metadata.
 */
export function CitationCard({ citation, compact = false }: CitationCardProps) {
  // @ts-ignore - i18n shim
  const t = useTranslations("chat.research");
  const {
    title,
    url,
    description,
    domain,
    relevance_score,
    accessed_at,
    source_type,
  } = citation;

  // Format access date
  const formattedDate = useMemo(() => {
    if (!accessed_at) return null;
    try {
      const date = new Date(accessed_at);
      return date.toLocaleDateString(undefined, {
        year: "numeric",
        month: "short",
        day: "numeric",
      });
    } catch {
      return accessed_at.slice(0, 10);
    }
  }, [accessed_at]);

  // Format relevance score as percentage
  const relevancePercent = useMemo(() => {
    if (relevance_score == null || relevance_score <= 0) return null;
    return Math.round(relevance_score * 100);
  }, [relevance_score]);

  return (
    <span className={cn("block space-y-2", compact && "space-y-1")}>
      {/* Title */}
      <span className="block font-semibold text-sm line-clamp-2 leading-snug">
        {title}
      </span>

      {/* Domain and metadata row */}
      <span className="flex items-center gap-3 text-xs text-muted-foreground">
        {domain && (
          <span className="flex items-center gap-1">
            <Globe className="h-3 w-3" />
            {domain}
          </span>
        )}
        {formattedDate && (
          <span className="flex items-center gap-1">
            <Clock className="h-3 w-3" />
            {formattedDate}
          </span>
        )}
        {relevancePercent != null && (
          <span className="flex items-center gap-1">
            <Star className="h-3 w-3" />
            {relevancePercent}% match
          </span>
        )}
      </span>

      {/* Description/snippet */}
      {description && !compact && (
        <span className="block text-xs text-muted-foreground line-clamp-3 leading-relaxed">
          {description}
        </span>
      )}

      {/* Source type badge */}
      {source_type && (
        <span className="inline-flex items-center px-1.5 py-0.5 rounded text-[10px] bg-secondary text-secondary-foreground">
          {source_type === "web_search" ? t("sourceTypeWeb") : source_type}
        </span>
      )}

      {/* URL preview */}
      <span className="block text-[10px] text-muted-foreground truncate opacity-60">
        {url}
      </span>
    </span>
  );
}

interface CitationListProps {
  citations: Citation[];
  title?: string;
  className?: string;
}

/**
 * List component for displaying all citations.
 */
export function CitationList({
  citations,
  title,
  className,
}: CitationListProps) {
  // @ts-ignore - i18n shim
  const t = useTranslations("chat.research");
  const resolvedTitle = title ?? t("citationSources");

  if (!citations || citations.length === 0) {
    return null;
  }

  return (
    <div className={cn("space-y-3", className)}>
      <h3 className="text-sm font-semibold text-foreground">{resolvedTitle}</h3>
      <div className="space-y-2">
        {citations.map((citation, index) => (
          <div
            key={citation.url || index}
            className="p-3 rounded-lg border bg-card hover:bg-accent/50 transition-colors"
          >
            <div className="flex items-start gap-3">
              <span className="flex-shrink-0 w-6 h-6 rounded-full bg-primary/10 text-primary text-xs font-medium flex items-center justify-center">
                {index + 1}
              </span>
              <div className="flex-1 min-w-0">
                <a
                  href={citation.url}
                  target="_blank"
                  rel="noopener noreferrer"
                  className="text-sm font-medium text-foreground hover:text-primary hover:underline line-clamp-1"
                >
                  {citation.title}
                </a>
                {citation.domain && (
                  <p className="text-xs text-muted-foreground mt-0.5">
                    {citation.domain}
                  </p>
                )}
                {citation.description && (
                  <p className="text-xs text-muted-foreground mt-1 line-clamp-2">
                    {citation.description}
                  </p>
                )}
              </div>
            </div>
          </div>
        ))}
      </div>
    </div>
  );
}

interface CitationBadgeProps {
  number: number;
  citation?: Citation;
  onClick?: () => void;
}

/**
 * Small numbered badge for inline citations.
 */
export function CitationBadge({ number, citation, onClick }: CitationBadgeProps) {
  const badge = (
    <button
      onClick={onClick}
      className="inline-flex items-center justify-center w-4 h-4 rounded-full bg-primary/10 text-primary text-[10px] font-medium hover:bg-primary/20 transition-colors align-super ml-0.5 cursor-pointer"
    >
      {number}
    </button>
  );

  if (!citation) {
    return badge;
  }

  return (
    <HoverCard openDelay={200} closeDelay={100}>
      <HoverCardTrigger asChild>{badge}</HoverCardTrigger>
      <HoverCardContent className="w-72 p-3" side="top" sideOffset={4}>
        <CitationCard citation={citation} compact />
      </HoverCardContent>
    </HoverCard>
  );
}
