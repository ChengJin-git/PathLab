import { useTranslations } from "../../lib/deep-research/i18n";
import { useMemo } from "react";
import { useStore, useToolCalls } from "../../lib/deep-research/store";
import { parseJSON } from "../../lib/deep-research/utils/json";
import { Tooltip } from "./tooltip";
import { LINK_STYLE, linkHoverHandlers } from "./citation";

export const Link = ({
  href,
  children,
  checkLinkCredibility = false,
}: {
  href: string | undefined;
  children: React.ReactNode;
  checkLinkCredibility: boolean;
}) => {
  const toolCalls = useToolCalls();
  const responding = useStore((state) => state.responding);

  const credibleLinks = useMemo(() => {
    const links = new Set<string>();
    if (!checkLinkCredibility) return links;

    (toolCalls || []).forEach((call) => {
      if (call && call.name === "web_search" && call.result) {
        try {
          const result = parseJSON(call.result, []) as Array<{ url: string }>;
          if (Array.isArray(result)) {
            result.forEach((r) => {
              if (r && typeof r.url === 'string') {
                // encodeURI is used to handle the case where the link contains chinese or other special characters
                links.add(encodeURI(r.url));
                links.add(r.url);
              }
            });
          }
        } catch (error) {
          console.warn('Failed to parse web_search result:', error);
        }
      }
    });
    return links;
  }, [toolCalls]);

  const isCredible = useMemo(() => {
    return checkLinkCredibility && href && !responding
      ? credibleLinks.has(href)
      : true;
  }, [credibleLinks, href, responding, checkLinkCredibility]);

  const handleClick = (e: React.MouseEvent<HTMLAnchorElement>) => {
    if (!href) return;
    e.preventDefault();
    e.stopPropagation();
    window.open(href, "_blank", "noopener,noreferrer");
  };

  const t = useTranslations("common");
  const linkNode = (
    <a
      href={href}
      target="_blank"
      rel="noopener noreferrer"
      onClick={handleClick}
      style={{
        ...LINK_STYLE,
        borderRadius: "2px",
        ...(isCredible
          ? {}
          : {
            color: "#b45309",
            textDecorationColor: "rgba(217, 119, 6, 0.45)",
            textDecorationStyle: "dotted",
          }),
      }}
      {...linkHoverHandlers}
    >
      {children}
    </a>
  );

  return (
    !isCredible ? (
      <Tooltip title={t("linkNotReliable")} delayDuration={300}>
        <span style={{ display: "inline" }}>{linkNode}</span>
      </Tooltip>
    ) : (
      <span style={{ display: "inline" }}>{linkNode}</span>
    )
  );
};
