export function autoFixMarkdown(markdown: string): string {
  let fixed = markdown;
  // Convert raw HTML anchor targets (e.g. `<a id="ref-1"></a> [1]`) to the
  // markdown-compatible format `[[1]](#citation-target-1)` which the Markdown
  // component's `a` handler renders as a styled anchor with id="ref-1".
  // react-markdown does not render raw HTML by default, so these tags appear
  // as literal text without this conversion.
  fixed = fixed.replace(
    /<a\s+id=["']ref-(\d+)["']\s*(?:\/>|><\/a>)\s*\[(\d+)\]/g,
    (_match, _id, num) => `[[${num}]](#citation-target-${num})`,
  );
  // Strip any remaining bare HTML anchor tags that weren't followed by [N]
  fixed = fixed.replace(/<a\s+id=["']ref-\d+["']\s*(?:\/>|><\/a>)\s*/g, "");
  return autoCloseTrailingLink(fixed);
}

export function linkifyBareInlineCitations(markdown: string): string {
  const lines = markdown.split("\n");
  let inCodeBlock = false;
  let inReferenceSection = false;

  return lines.map((line) => {
    const trimmed = line.trim();

    if (trimmed.startsWith("```")) {
      inCodeBlock = !inCodeBlock;
      return line;
    }

    if (!inCodeBlock) {
      if (/^#{1,6}\s+(references|key citations)\s*$/i.test(trimmed)) {
        inReferenceSection = true;
        return line;
      }

      if (inReferenceSection && /^#{1,6}\s+/.test(trimmed)) {
        inReferenceSection = false;
      }
    }

    if (inCodeBlock || inReferenceSection) {
      return line;
    }

    let nextLine = line;

    nextLine = nextLine.replace(
      /\[(\d{1,3}(?:\s*,\s*\d{1,3})+)\](?!\()/g,
      (_match, inner: string) => inner
        .split(",")
        .map((value) => {
          const index = value.trim();
          return `[${index}](#cite-${index})`;
        })
        .join(""),
    );

    nextLine = nextLine.replace(
      /\[\[(\d{1,3})(?:\s*,\s*(p\.?[^\]]+))?\]\](?!\()/gi,
      (_match, index: string, pageInfo?: string) => pageInfo
        ? `[[${index}, ${pageInfo.trim()}]](#cite-${index})`
        : `[[${index}]](#cite-${index})`,
    );

    nextLine = nextLine.replace(
      /\[(\d{1,3}),\s*(p\.?[^\]]+)\](?!\()/gi,
      (_match, index: string, pageInfo: string) => `[${index}, ${pageInfo.trim()}](#cite-${index})`,
    );

    nextLine = nextLine.replace(
      /\[(\d{1,3})\](?!\()/g,
      (_match, index: string) => `[${index}](#cite-${index})`,
    );

    return nextLine;
  }).join("\n");
}

/**
 * Normalize math delimiters for display consumption
 * Ensures all math delimiters are in $$ format for remarkMath/rehypeKatex
 * This is used by the Markdown display component
 */
export function normalizeMathForDisplay(markdown: string): string {
  let normalized = markdown;
  
  // Convert all LaTeX-style delimiters to $$
  // Both display and inline math use $$ for display component (remarkMath handles both)
  // Handle double backslash first to avoid conflicts
  normalized = normalized
    .replace(/\\\\\[([^\]]*)\\\\\]/g, (_match, content) => `$$${content}$$`)  // \\[...\\] → $$...$$
    .replace(/\\\[([^\]]*)\\\]/g, (_match, content) => `$$${content}$$`)      // \[...\] → $$...$$
    .replace(/\\\\\(([^)]*)\\\\\)/g, (_match, content) => `$$${content}$$`)   // \\(...\\) → $$...$$
    .replace(/\\\(([^)]*)\\\)/g, (_match, content) => `$$${content}$$`);       // \(...\) → $$...$$
  
  // Replace double backslashes with single in math contexts
  // For inline math: $...$
  normalized = normalized.replace(
    /\$([^\$]+?)\$/g,
    (match, mathContent) => {
      return `$${mathContent.replace(/\\\\/g, '\\')}$`;
    }
  );
  
  // For display math: $$...$$
  normalized = normalized.replace(
    /\$\$([\s\S]+?)\$\$/g,
    (match, mathContent) => {
      return `$$${mathContent.replace(/\\\\/g, '\\')}$$`;
    }
  );
    
  return normalized;
}

function autoCloseTrailingLink(markdown: string): string {
  // Fix unclosed Markdown links or images
  let fixedMarkdown: string = markdown;

  // Fix unclosed image syntax ![...](...)
  fixedMarkdown = fixedMarkdown.replace(
    /!\[([^\]]*)\]\(([^)]*)$/g,
    (match: string, altText: string, url: string): string => {
      return `![${altText}](${url})`;
    },
  );

  // Fix unclosed link syntax [...](...)
  fixedMarkdown = fixedMarkdown.replace(
    /\[([^\]]*)\]\(([^)]*)$/g,
    (match: string, linkText: string, url: string): string => {
      return `[${linkText}](${url})`;
    },
  );

  // Fix unclosed image syntax ![...]
  fixedMarkdown = fixedMarkdown.replace(
    /!\[([^\]]*)$/g,
    (match: string, altText: string): string => {
      return `![${altText}]`;
    },
  );

  // Fix unclosed link syntax [...]
  fixedMarkdown = fixedMarkdown.replace(
    /\[([^\]]*)$/g,
    (match: string, linkText: string): string => {
      return `[${linkText}]`;
    },
  );

  return fixedMarkdown;
}
