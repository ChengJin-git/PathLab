// Copyright (c) 2025 Bytedance Ltd. and/or its affiliates
// SPDX-License-Identifier: MIT

import type { Citation, Option } from "../messages";

// Tool Calls

export interface ToolCall {
  type: "tool_call";
  id: string;
  name: string;
  args: Record<string, unknown>;
}

export interface ToolCallChunk {
  type: "tool_call_chunk";
  index: number;
  id: string;
  name: string;
  args: string;
}

// Events

interface GenericEvent<T extends string, D extends object> {
  type: T;
  data: {
    id: string;
    thread_id: string;
    agent: "coordinator" | "planner" | "researcher" | "coder" | "reporter";
    role: "user" | "assistant" | "tool";
    finish_reason?: "stop" | "tool_calls" | "interrupt";
  } & D;
}

export interface MessageChunkEvent
  extends GenericEvent<
    "message_chunk",
    {
      content?: string;
      reasoning_content?: string;
    }
  > { }

export interface ToolCallsEvent
  extends GenericEvent<
    "tool_calls",
    {
      tool_calls: ToolCall[];
      tool_call_chunks: ToolCallChunk[];
    }
  > { }

export interface ToolCallChunksEvent
  extends GenericEvent<
    "tool_call_chunks",
    {
      tool_call_chunks: ToolCallChunk[];
    }
  > { }

export interface ToolCallResultEvent
  extends GenericEvent<
    "tool_call_result",
    {
      tool_call_id: string;
      content?: string;
    }
  > { }

export interface InterruptEvent
  extends GenericEvent<
    "interrupt",
    {
      options: Option[];
    }
  > { }

export interface CitationsEvent {
  type: "citations";
  data: {
    thread_id: string;
    citations: Citation[];
  };
}

export interface TokenUsageEvent {
  type: "token_usage";
  data: {
    thread_id: string;
    total_prompt_tokens: number;
    total_completion_tokens: number;
    total_tokens: number;
    total_calls: number;
    by_agent: Record<
      string,
      {
        prompt_tokens: number;
        completion_tokens: number;
        total_tokens: number;
        calls: number;
      }
    >;
    details: Array<{
      agent: string;
      node: string;
      prompt_tokens: number;
      completion_tokens: number;
      total_tokens: number;
      model: string;
    }>;
  };
}

export interface ErrorEvent {
  type: "error";
  data: {
    thread_id: string;
    error: string;
  };
}

export interface CancelledEvent {
  type: "cancelled";
  data: {
    thread_id?: string;
  };
}

export interface JobCreatedEvent {
  type: "job_created";
  data: { job_id: string };
}

export interface CursorUpdateEvent {
  type: "cursor_update";
  data: { cursor: number };
}

export type ChatEvent =
  | MessageChunkEvent
  | ToolCallsEvent
  | ToolCallChunksEvent
  | ToolCallResultEvent
  | InterruptEvent
  | CitationsEvent
  | TokenUsageEvent
  | ErrorEvent
  | CancelledEvent
  | JobCreatedEvent
  | CursorUpdateEvent;
