// Copyright (c) 2025 Bytedance Ltd. and/or its affiliates
// SPDX-License-Identifier: MIT

import { z } from "zod";

export const MCPConfigSchema = z.object({
  mcpServers: z.record(
    z.string(),
    z.union([
      z.object({
        command: z.string({
          message: "`command` must be a string",
        }),
        args: z
          .array(z.string(), {
            message: "`args` must be an array of strings",
          })
          .optional(),
        env: z.record(z.string(), z.string()).optional(),
      }),
      z.object({
        url: z
          .string({
            message:
              "`url` must be a valid URL starting with http:// or https://",
          })
          .refine(
            (value) => {
              try {
                const url = new URL(value);
                return url.protocol === "http:" || url.protocol === "https:";
              } catch {
                return false;
              }
            },
            {
              message:
                "`url` must be a valid URL starting with http:// or https://",
            },
          ),
        env: z.record(z.string(), z.string()).optional(),
        headers: z.record(z.string(), z.string()).optional(),
        timeout: z
          .number({
            message: "`timeout` must be a number",
          })
          .int()
          .positive()
          .optional(),
        sse_read_timeout: z
          .number({
            message: "`sse_read_timeout` must be a number",
          })
          .int()
          .positive()
          .optional(),
        transport: z
          .enum(["sse", "streamable_http"], {
            message: "transport must be either sse or streamable_http"
          })
          .default("sse"),
      }),
    ]),
  ),
});
