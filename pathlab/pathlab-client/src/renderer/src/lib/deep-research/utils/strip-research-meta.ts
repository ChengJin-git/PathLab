// Copyright (c) 2025 Bytedance Ltd. and/or its affiliates
// SPDX-License-Identifier: MIT

export const RESEARCH_META_RE = /\n?\[PATHLAB_RESEARCH_META\][\s\S]*?\[\/PATHLAB_RESEARCH_META\]\n?/g;
export const INTERNAL_TOOL_REPLAY_BLOCK_RE = /\n?\[PATHLAB_INTERNAL_TOOL_REPLAY\][\s\S]*?\[\/PATHLAB_INTERNAL_TOOL_REPLAY\]\n?/gi;
const INLINE_TOOL_CALL_TRACE_RE = /Called tool:\s+.*?(?=(?:\s+Called tool:|\s+Tool result from|\n{2,}|$))/gis;
const TOOL_RESULT_TRACE_RE = /Tool result from\s+.*?(?=(?:\n{2,}|\s+Called tool:|$))/gis;

export function stripResearchMeta(content: string): string {
  return content
    .replace(RESEARCH_META_RE, "\n")
    .replace(/\n{3,}/g, "\n\n")
    .trim();
}

export function stripInternalToolReplayContent(content: string): string {
  return content
    .replace(INTERNAL_TOOL_REPLAY_BLOCK_RE, "\n")
    .replace(INLINE_TOOL_CALL_TRACE_RE, " ")
    .replace(TOOL_RESULT_TRACE_RE, "\n")
    .replace(/[ \t]{2,}/g, " ")
    .replace(/\n[ \t]+/g, "\n")
    .replace(/\n{3,}/g, "\n\n")
    .trim();
}