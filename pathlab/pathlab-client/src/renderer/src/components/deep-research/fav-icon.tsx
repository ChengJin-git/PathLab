// Copyright (c) 2025 Bytedance Ltd. and/or its affiliates
// SPDX-License-Identifier: MIT

import { cn } from "../../lib/utils";

const FALLBACK_FAVICON =
  "https://perishablepress.com/wp/wp-content/images/2021/favicon-standard.png";

function safeFaviconSrc(url: string): string {
  try {
    return new URL(url).origin + "/favicon.ico";
  } catch {
    return FALLBACK_FAVICON;
  }
}

export function FavIcon({
  className,
  url,
  title,
}: {
  className?: string;
  url: string;
  title?: string;
}) {
  return (
    <img
      className={cn("bg-accent h-4 w-4 rounded-full shadow-sm", className)}
      width={16}
      height={16}
      src={safeFaviconSrc(url)}
      alt={title}
      onError={(e) => {
        e.currentTarget.src = FALLBACK_FAVICON;
      }}
    />
  );
}
