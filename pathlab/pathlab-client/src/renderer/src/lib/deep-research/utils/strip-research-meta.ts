// Copyright (c) 2025 Bytedance Ltd. and/or its affiliates
// SPDX-License-Identifier: MIT

export const RESEARCH_META_RE = /\n?\[PATHLAB_RESEARCH_META\][\s\S]*?\[\/PATHLAB_RESEARCH_META\]\n?/g;

export function stripResearchMeta(content: string): string {
  return content
    .replace(RESEARCH_META_RE, "\n")
    .replace(/\n{3,}/g, "\n\n")
    .trim();
}