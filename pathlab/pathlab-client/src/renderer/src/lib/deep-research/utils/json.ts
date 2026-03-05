import { parse } from "best-effort-json-parser";

function bestEffortParseSilently(input: string): unknown {
  const prev = parse.onExtraToken;
  parse.onExtraToken = undefined;
  try {
    return parse(input);
  } finally {
    parse.onExtraToken = prev;
  }
}

/**
 * Extract valid JSON from content that may have extra tokens.
 * Finds the last closing brace/bracket that could be valid JSON.
 */
function extractValidJSON(content: string): string {
  let braceCount = 0;
  let bracketCount = 0;
  let inString = false;
  let lastValidEnd = -1;

  for (let i = 0; i < content.length; i++) {
    const char = content[i];

    if (inString) {
      // Inside a JSON string: only react to escape sequences and closing quote.
      if (char === "\\" && i + 1 < content.length) {
        i++; // skip the escaped character
        continue;
      }
      if (char === '"') {
        inString = false;
      }
      continue;
    }

    // Outside of strings
    if (char === '"') {
      inString = true;
    } else if (char === "{") {
      braceCount++;
    } else if (char === "}") {
      if (braceCount > 0) {
        braceCount--;
        if (braceCount === 0) {
          lastValidEnd = i;
        }
      }
    } else if (char === "[") {
      bracketCount++;
    } else if (char === "]") {
      if (bracketCount > 0) {
        bracketCount--;
        if (bracketCount === 0) {
          lastValidEnd = i;
        }
      }
    }
  }

  if (lastValidEnd > 0) {
    return content.substring(0, lastValidEnd + 1);
  }

  return content;
}

export function parseJSON<T>(json: string | null | undefined, fallback: T) {
  if (!json) {
    return fallback;
  }
  try {
    let raw = json
      .trim()
      .replace(/^```json\s*/, "")
      .replace(/^```js\s*/, "")
      .replace(/^```ts\s*/, "")
      .replace(/^```plaintext\s*/, "")
      .replace(/^```\s*/, "")
      .replace(/\s*```$/, "");

    // Fast path: try native JSON.parse first.  This is the most reliable
    // parser and avoids extractValidJSON which can corrupt content when the
    // LLM produces unescaped double-quotes inside string values.
    try {
      return JSON.parse(raw) as T;
    } catch {
      // Not valid JSON — fall through to lenient parsers.
    }

    // Second attempt: extract valid JSON to remove extra tokens, then
    // use best-effort parser for incomplete/malformed content.
    if (raw.startsWith("{") || raw.startsWith("[")) {
      raw = extractValidJSON(raw);
    }

    // Parse the cleaned content
    return bestEffortParseSilently(raw) as T;
  } catch {
    // Fallback: try to extract meaningful content from malformed JSON
    // This is a last-resort attempt to salvage partial data
    return fallback;
  }
}
