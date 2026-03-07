// Copyright (c) 2025 Bytedance Ltd. and/or its affiliates
// SPDX-License-Identifier: MIT

import { cn } from "../../lib/utils";

import styles from "./loading-animation.module.css";

export function LoadingAnimation({
  className,
  size = "normal",
  tone = "primary",
}: {
  className?: string;
  size?: "normal" | "sm";
  tone?: "primary" | "muted";
}) {
  return (
    <div
      className={cn(
        styles.loadingAnimation,
        size === "sm" && styles.sm,
        tone === "primary" ? "text-primary-500" : "text-gray-400",
        className,
      )}
    >
      <div></div>
      <div></div>
      <div></div>
    </div>
  );
}
