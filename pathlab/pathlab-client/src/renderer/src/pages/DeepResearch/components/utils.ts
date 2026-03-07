import { parse as bestEffortParse } from "best-effort-json-parser";
import { parseJSON } from "../../../lib/deep-research/utils";

export function parsePlannerPayload(content: string): {
    title?: string;
    thought?: string;
    steps?: { title?: string; description?: string; tools?: string[] }[];
} | null {
    const trimmed = (content ?? "").trim();
    if (!trimmed) return null;

    const fencedMatch = trimmed.match(/```(?:json)?\s*([\s\S]*?)(?:```|$)/i);
    const candidate = fencedMatch ? fencedMatch[1]?.trim() ?? "" : trimmed;
    const looksLikeJsonEnvelope = /^[\[{]/.test(candidate);
    const looksLikePlanHints =
        (candidate.includes("\"step_type\"") && candidate.includes("\"need_search\"")) ||
        (candidate.includes("\"has_enough_context\"") && candidate.includes("\"steps\"")) ||
        (candidate.includes("\"thought\"") && candidate.includes("\"steps\"")) ||
        candidate.includes("\"thought\"") ||
        candidate.includes("\"title\"");

    if (!fencedMatch && !looksLikeJsonEnvelope && !looksLikePlanHints) {
        return null;
    }

    try {
        const parsed = parseJSON<{
            title?: string;
            thought?: string;
            steps?: Array<{ title?: string; description?: string; tools?: string[] }>;
            has_enough_context?: boolean;
        } | null>(candidate, null);
        if (
            parsed &&
            (
                Array.isArray(parsed.steps) ||
                typeof parsed.has_enough_context === "boolean" ||
                typeof parsed.thought === "string" ||
                typeof parsed.title === "string"
            )
        ) {
            return parsed;
        }
    } catch {
        // ignore
    }

    try {
        const bestEffort = bestEffortParse(candidate) as any;
        if (bestEffort && typeof bestEffort === "object") {
            const stepsList = Array.isArray(bestEffort.steps) ? bestEffort.steps : [];
            const parsedSteps = stepsList.map((s: any) => ({
                title: s?.title ?? "",
                description: s?.description ?? "",
                tools: s?.tools ?? [],
            }));

            if (
                parsedSteps.length > 0 ||
                typeof bestEffort.thought === "string" ||
                typeof bestEffort.title === "string"
            ) {
                return {
                    title: bestEffort.title ?? "",
                    thought: bestEffort.thought ?? "",
                    steps: parsedSteps,
                };
            }
        }
    } catch {
        // ignore
    }

    const thoughtMatch = candidate.match(
        /"thought"\s*:\s*"([\s\S]*?)(?:"\s*,\s*"(?:title|steps|has_enough_context)"|"\s*[,}]|"$)/,
    );
    if (thoughtMatch) {
        return {
            title: "",
            thought: thoughtMatch[1] ?? "",
            steps: [],
        };
    }

    // Extra fallback: native JSON.parse for content with special characters
    // (Chinese text, markdown symbols, etc.) that may trip up extractValidJSON
    // but are still valid JSON.
    if (looksLikeJsonEnvelope && (
        candidate.includes("\"steps\"") &&
        (candidate.includes("\"thought\"") || candidate.includes("\"title\""))
    )) {
        try {
            const nativeParsed = JSON.parse(candidate) as any;
            if (nativeParsed && typeof nativeParsed === "object" && (
                Array.isArray(nativeParsed.steps) ||
                typeof nativeParsed.thought === "string" ||
                typeof nativeParsed.title === "string"
            )) {
                return {
                    title: nativeParsed.title ?? "",
                    thought: nativeParsed.thought ?? "",
                    steps: Array.isArray(nativeParsed.steps) ? nativeParsed.steps : [],
                };
            }
        } catch {
            // ignore – content may be incomplete during streaming
        }
    }

    // Lenient fallback for early streaming: if the candidate starts with `{`
    // and contains at least one recognisable planner key (even partially), treat
    // it as an in-progress plan so PlanCard renders instead of raw JSON.
    if (looksLikeJsonEnvelope && (
        candidate.includes("\"has_enough_context\"") ||
        candidate.includes("\"locale\"") ||
        candidate.includes("\"step_type\"")
    )) {
        return { title: "", thought: "", steps: [] };
    }
    return null;
}
