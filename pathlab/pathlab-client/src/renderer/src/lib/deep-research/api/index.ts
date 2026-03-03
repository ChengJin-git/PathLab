export * from "./chat";
export * from "./hooks";
export * from "./types";

// Prompt enhancer (simplified)
export async function enhancePrompt(prompt: string, context?: string, reportStyle?: string): Promise<string> {
  // TODO: Implement via gateway proxy if needed
  return prompt;
}

// Evaluation result type
export interface EvaluationResult {
  overall_score: number;
  metrics: {
    word_count: number;
    citation_count: number;
    unique_sources: number;
    image_count: number;
    section_coverage: Record<string, boolean>;
  };
  llm_evaluation?: {
    scores: Record<string, number>;
    strengths: string[];
    weaknesses: string[];
  };
}

