import { useCallback, useState } from "react";
import {
    Document,
    Packer,
    Paragraph,
    TextRun,
    HeadingLevel,
    ExternalHyperlink,
} from "docx";
import DOMPurify from "dompurify";
import { saveAs } from "file-saver";
import html2canvas from "html2canvas";
import { jsPDF } from "jspdf";
import { marked } from "marked";
import { toast } from "sonner";

import { useTranslations } from "../../../lib/deep-research/i18n";
import { useStore } from "../../../lib/deep-research/store";

export function useReportExporter(reportId?: string) {
    // @ts-ignore - i18n shim
    const t = useTranslations("chat.research");
    const [isDownloading, setIsDownloading] = useState(false);
    const [copied, setCopied] = useState(false);

    const handleCopy = useCallback(() => {
        if (!reportId) {
            return;
        }
        const report = useStore.getState().messages.get(reportId);
        if (!report) {
            return;
        }
        void navigator.clipboard.writeText(report.content);
        setCopied(true);
        setTimeout(() => {
            setCopied(false);
        }, 1000);
    }, [reportId]);

    // Helper function to generate timestamp for filenames
    const getTimestamp = useCallback(() => {
        const now = new Date();
        const pad = (n: number) => n.toString().padStart(2, "0");
        return `${now.getFullYear()}-${pad(now.getMonth() + 1)}-${pad(now.getDate())}_${pad(now.getHours())}-${pad(now.getMinutes())}-${pad(now.getSeconds())}`;
    }, []);

    // Helper function to trigger file download
    const triggerDownload = useCallback(
        (content: string, filename: string, mimeType: string) => {
            const blob = new Blob([content], { type: mimeType });
            const url = URL.createObjectURL(blob);
            const a = document.createElement("a");
            a.href = url;
            a.download = filename;
            document.body.appendChild(a);
            a.click();
            setTimeout(() => {
                try {
                    if (a.parentNode) {
                        a.parentNode.removeChild(a);
                    }
                } finally {
                    URL.revokeObjectURL(url);
                }
            }, 100);
        },
        [],
    );

    // Download report as Markdown
    const handleDownloadMarkdown = useCallback(() => {
        if (!reportId) return;
        const report = useStore.getState().messages.get(reportId);
        if (!report) return;
        triggerDownload(
            report.content,
            `research-report-${getTimestamp()}.md`,
            "text/markdown",
        );
    }, [reportId, getTimestamp, triggerDownload]);

    // Download report as HTML
    const handleDownloadHTML = useCallback(() => {
        if (!reportId) return;
        const report = useStore.getState().messages.get(reportId);
        if (!report) return;
        const rawHtml = marked(report.content) as string;
        const htmlContent = DOMPurify.sanitize(rawHtml);
        const fullHTML = `<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="UTF-8">
  <meta name="viewport" content="width=device-width, initial-scale=1.0">
  <title>Research Report</title>
  <style>
    body { font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif; max-width: 800px; margin: 0 auto; padding: 20px; line-height: 1.6; }
    h1, h2, h3 { color: #333; }
    code { background: #f4f4f4; padding: 2px 6px; border-radius: 4px; }
    pre { background: #f4f4f4; padding: 16px; border-radius: 8px; overflow-x: auto; }
    blockquote { border-left: 4px solid #ddd; margin: 0; padding-left: 16px; color: #666; }
    table { border-collapse: collapse; width: 100%; }
    th, td { border: 1px solid #ddd; padding: 8px; text-align: left; }
    th { background: #f4f4f4; }
  </style>
</head>
<body>
${htmlContent}
</body>
</html>`;
        triggerDownload(
            fullHTML,
            `research-report-${getTimestamp()}.html`,
            "text/html",
        );
    }, [reportId, getTimestamp, triggerDownload]);

    // Download report as PDF using an isolated iframe to avoid Tailwind CSS conflicts
    const handleDownloadPDF = useCallback(async () => {
        if (!reportId || isDownloading) return;
        const report = useStore.getState().messages.get(reportId);
        if (!report) return;

        setIsDownloading(true);
        let iframe: HTMLIFrameElement | null = null;
        try {
            // Convert markdown to HTML
            const rawHtml = marked(report.content) as string;
            const htmlContent = DOMPurify.sanitize(rawHtml);

            // Use an iframe to completely isolate from page CSS (avoids lab() color parsing errors)
            iframe = document.createElement("iframe");
            iframe.style.cssText = "position: absolute; left: -9999px; top: 0; width: 794px; height: 0; border: none;";
            document.body.appendChild(iframe);

            const iframeDoc = iframe.contentDocument ?? iframe.contentWindow?.document;
            if (!iframeDoc) throw new Error("Cannot access iframe document");

            iframeDoc.open();
            iframeDoc.write(`<!DOCTYPE html>
<html><head><style>
  body {
    margin: 0; padding: 40px 50px;
    font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', 'Noto Sans SC', 'PingFang SC', 'Microsoft YaHei', Roboto, sans-serif;
    font-size: 14px; line-height: 1.8; background: #fff; color: #000;
  }
  h1 { font-size: 24px; margin: 20px 0 12px; font-weight: 700; }
  h2 { font-size: 20px; margin: 18px 0 10px; font-weight: 600; }
  h3 { font-size: 17px; margin: 14px 0 8px; font-weight: 600; }
  h4 { font-size: 15px; margin: 12px 0 6px; font-weight: 600; }
  p { margin: 6px 0; }
  ul, ol { padding-left: 24px; margin: 6px 0; }
  li { margin: 3px 0; }
  a { color: #0066cc; text-decoration: underline; }
  code { background: #f5f5f5; padding: 2px 5px; border-radius: 3px; font-size: 13px; }
  pre { background: #f5f5f5; padding: 14px; border-radius: 6px; overflow-x: auto; font-size: 13px; }
  blockquote { border-left: 4px solid #ddd; margin: 8px 0; padding-left: 16px; color: #555; }
  table { border-collapse: collapse; width: 100%; margin: 10px 0; font-size: 13px; }
  th, td { border: 1px solid #ddd; padding: 8px 10px; text-align: left; }
  th { background: #f4f4f4; font-weight: 600; }
  img { max-width: 100%; height: auto; }
  hr { border: none; border-top: 1px solid #eee; margin: 16px 0; }
</style></head><body>${htmlContent}</body></html>`);
            iframeDoc.close();

            // Wait for fonts/images to load
            await new Promise((resolve) => setTimeout(resolve, 500));

            // Resize iframe to content height
            const contentEl = iframeDoc.body;
            iframe.style.height = contentEl.scrollHeight + "px";

            // Render to canvas inside the clean iframe context
            const canvas = await html2canvas(contentEl, {
                scale: 2,
                useCORS: true,
                logging: false,
                backgroundColor: "#ffffff",
                windowWidth: 794,
                windowHeight: contentEl.scrollHeight,
            });

            // Calculate PDF pages from the canvas
            const imgWidth = 210; // A4 width in mm
            const pageHeight = 297; // A4 height in mm
            const marginMm = 10;
            const contentWidth = imgWidth - 2 * marginMm;
            const imgHeight = (canvas.height * contentWidth) / canvas.width;
            const contentPageHeight = pageHeight - 2 * marginMm;

            const pdf = new jsPDF("p", "mm", "a4");
            let heightLeft = imgHeight;
            let position = marginMm;
            const imgData = canvas.toDataURL("image/png");

            // First page
            pdf.addImage(imgData, "PNG", marginMm, position, contentWidth, imgHeight);
            heightLeft -= contentPageHeight;

            // Additional pages
            while (heightLeft > 0) {
                position = -(imgHeight - heightLeft) + marginMm;
                pdf.addPage();
                pdf.addImage(imgData, "PNG", marginMm, position, contentWidth, imgHeight);
                heightLeft -= contentPageHeight;
            }

            pdf.save(`research-report-${getTimestamp()}.pdf`);
        } catch (error) {
            console.error("Failed to generate PDF:", error);
            toast.error(t("exportFailed"));
        } finally {
            try {
                iframe?.parentNode?.removeChild(iframe);
            } catch {
                // cleanup errors are harmless
            }
            setIsDownloading(false);
        }
    }, [reportId, getTimestamp, isDownloading, t]);

    // Helper function to parse inline markdown formatting for Word export
    const parseInlineMarkdown = useCallback(
        (text: string): (TextRun | ExternalHyperlink)[] => {
            // Process text recursively using marked's inline lexer
            const runs: (TextRun | ExternalHyperlink)[] = [];

            try {
                // Use marked's Lexer to safely parse inline markdown
                const tokens = marked.Lexer.lexInline(text);

                interface MarkedToken {
                    type: string;
                    text?: string;
                    tokens?: MarkedToken[];
                    href?: string;
                }

                const processTokens = (tokens: MarkedToken[]): void => {
                    for (const token of tokens) {
                        if (token.type === "text") {
                            // Regular text
                            if (token.text) {
                                runs.push(new TextRun(token.text));
                            }
                        } else if (token.type === "strong") {
                            // Bold text - may contain nested tokens
                            if (token.tokens && token.tokens.length > 0) {
                                // Process nested tokens and mark them as bold
                                const nestedRuns: TextRun[] = [];
                                for (const nestedToken of token.tokens) {
                                    if (nestedToken.type === "text") {
                                        nestedRuns.push(
                                            new TextRun({ text: nestedToken.text, bold: true }),
                                        );
                                    } else if (nestedToken.type === "em") {
                                        // Bold + italic nested tokens
                                        nestedRuns.push(
                                            new TextRun({
                                                text: nestedToken.text,
                                                bold: true,
                                                italics: true,
                                            }),
                                        );
                                    }
                                }
                                runs.push(...nestedRuns);
                            } else {
                                runs.push(new TextRun({ text: token.text, bold: true }));
                            }
                        } else if (token.type === "em") {
                            // Italic text
                            runs.push(
                                new TextRun({
                                    text: token.text ?? token.tokens?.[0]?.text,
                                    italics: true,
                                }),
                            );
                        } else if (token.type === "codespan") {
                            // Inline code
                            if (token.text) {
                                runs.push(
                                    new TextRun({ text: token.text, font: "Courier New" }),
                                );
                            }
                        } else if (token.type === "link") {
                            // Link - use the link text or fallback to URL
                            const linkText = token.text ?? token.href ?? "";
                            const linkUrl = token.href ?? "";
                            if (linkUrl) {
                                runs.push(
                                    new ExternalHyperlink({
                                        children: [
                                            new TextRun({ text: linkText, style: "Hyperlink" }),
                                        ],
                                        link: linkUrl,
                                    }),
                                );
                            } else {
                                // Fallback to plain text if no URL
                                runs.push(new TextRun(linkText));
                            }
                        } else if (token.type === "space") {
                            // Preserve spaces
                            runs.push(new TextRun(" "));
                        }
                    }
                };

                processTokens(tokens);
            } catch (error) {
                // Fallback to simple text parsing if marked fails
                console.warn("Marked parsing failed, using fallback:", error);
                // Pattern to match: bold (**text**), italic (*text*), inline code (`text`), links [text](url)
                const pattern =
                    /(\*\*(.+?)\*\*)|(\*(.+?)\*)|(`(.+?)`)|\[(.+?)\]\((.+?)\)/g;
                let lastIndex = 0;
                let match;

                while ((match = pattern.exec(text)) !== null) {
                    // Add plain text before the match
                    if (match.index > lastIndex) {
                        runs.push(new TextRun(text.slice(lastIndex, match.index)));
                    }

                    if (match[1]) {
                        // Bold: **text**
                        const boldText = match[2] ?? "";
                        runs.push(new TextRun({ text: boldText, bold: true }));
                    } else if (match[3]) {
                        // Italic: *text*
                        const italicText = match[4] ?? "";
                        runs.push(new TextRun({ text: italicText, italics: true }));
                    } else if (match[5]) {
                        // Inline code: `text`
                        const codeText = match[6] ?? "";
                        runs.push(new TextRun({ text: codeText, font: "Courier New" }));
                    } else if (match[7] && match[8]) {
                        // Link: [text](url)
                        runs.push(
                            new ExternalHyperlink({
                                children: [
                                    new TextRun({ text: match[7] ?? "", style: "Hyperlink" }),
                                ],
                                link: match[8],
                            }),
                        );
                    }

                    lastIndex = pattern.lastIndex;
                }

                // Add remaining plain text
                if (lastIndex < text.length) {
                    runs.push(new TextRun(text.slice(lastIndex)));
                }
            }

            return runs.length > 0 ? runs : [new TextRun(text)];
        },
        [],
    );

    // Download report as Word document
    const handleDownloadWord = useCallback(async () => {
        if (!reportId || isDownloading) return;
        const report = useStore.getState().messages.get(reportId);
        if (!report) return;

        setIsDownloading(true);
        try {
            // Parse markdown content into paragraphs
            const lines = report.content.split("\n");
            const children: Paragraph[] = [];

            for (const line of lines) {
                if (line.startsWith("# ")) {
                    children.push(
                        new Paragraph({
                            children: parseInlineMarkdown(line.substring(2)),
                            heading: HeadingLevel.HEADING_1,
                        }),
                    );
                } else if (line.startsWith("## ")) {
                    children.push(
                        new Paragraph({
                            children: parseInlineMarkdown(line.substring(3)),
                            heading: HeadingLevel.HEADING_2,
                        }),
                    );
                } else if (line.startsWith("### ")) {
                    children.push(
                        new Paragraph({
                            children: parseInlineMarkdown(line.substring(4)),
                            heading: HeadingLevel.HEADING_3,
                        }),
                    );
                } else if (line.startsWith("- ") || line.startsWith("* ")) {
                    // Unordered list item
                    children.push(
                        new Paragraph({
                            children: parseInlineMarkdown(line.substring(2)),
                            bullet: { level: 0 },
                        }),
                    );
                } else if (/^\d+\.\s/.test(line)) {
                    // Ordered list item
                    const text = line.replace(/^\d+\.\s/, "");
                    children.push(
                        new Paragraph({
                            children: parseInlineMarkdown(text),
                            numbering: { reference: "default-numbering", level: 0 },
                        }),
                    );
                } else if (line.trim()) {
                    children.push(
                        new Paragraph({
                            children: parseInlineMarkdown(line),
                        }),
                    );
                } else {
                    children.push(new Paragraph({ text: "" }));
                }
            }

            const doc = new Document({
                numbering: {
                    config: [
                        {
                            reference: "default-numbering",
                            levels: [
                                {
                                    level: 0,
                                    format: "decimal",
                                    text: "%1.",
                                    alignment: "start",
                                },
                            ],
                        },
                    ],
                },
                sections: [{ children }],
            });

            const blob = await Packer.toBlob(doc);
            saveAs(blob, `research-report-${getTimestamp()}.docx`);
        } catch (error) {
            console.error("Failed to generate Word document:", error);
            toast.error(t("exportFailed"));
        } finally {
            setIsDownloading(false);
        }
    }, [reportId, getTimestamp, isDownloading, t, parseInlineMarkdown]);

    // Download report as Image
    const handleDownloadImage = useCallback(async () => {
        if (!reportId || isDownloading) return;
        const report = useStore.getState().messages.get(reportId);
        if (!report) return;

        setIsDownloading(true);
        let container: HTMLDivElement | null = null;
        try {
            // Create a temporary container with simple styles to avoid color parsing issues
            container = document.createElement("div");
            container.style.cssText =
                "position: absolute; left: -9999px; top: 0; width: 800px; padding: 40px; font-family: Arial, sans-serif; line-height: 1.6; background-color: #ffffff; color: #000000;";
            const styleTag =
                "<style>* { color: #000000; } h1,h2,h3,h4,h5,h6 { color: #333333; } a { color: #0066cc; } code { background-color: #f5f5f5; padding: 2px 4px; } pre { background-color: #f5f5f5; padding: 12px; }</style>";
            const rawHtml = marked(report.content) as string;
            const sanitizedHtml = DOMPurify.sanitize(rawHtml);
            container.innerHTML = styleTag + sanitizedHtml;
            document.body.appendChild(container);

            const canvas = await html2canvas(container, {
                scale: 2,
                useCORS: true,
                logging: false,
                backgroundColor: "#ffffff",
            });

            // Promisify toBlob for proper async handling
            const blob = await new Promise<Blob | null>((resolve) => {
                canvas.toBlob((b) => resolve(b), "image/png");
            });

            if (blob) {
                saveAs(blob, `research-report-${getTimestamp()}.png`);
            }
        } catch (error) {
            console.error("Failed to generate image:", error);
            toast.error(t("exportFailed"));
        } finally {
            // Ensure container is always removed
            try {
                container?.parentNode?.removeChild(container);
            } catch (error) {
                // Log cleanup errors for better debugging (not just in development)
                console.warn(
                    "Failed to remove temporary container during image export cleanup:",
                    error,
                );
                // Don't throw - cleanup failures are expected and harmless
            }
            setIsDownloading(false);
        }
    }, [reportId, getTimestamp, isDownloading, t]);

    return {
        isDownloading,
        copied,
        handleCopy,
        handleDownloadMarkdown,
        handleDownloadHTML,
        handleDownloadPDF,
        handleDownloadWord,
        handleDownloadImage,
    };
}
