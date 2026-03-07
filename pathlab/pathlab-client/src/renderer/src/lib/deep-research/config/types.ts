export interface ModelConfig {
  basic: string[];
  reasoning: string[];
}

export interface RagConfig {
  provider: string;
}

export interface AppConfig {
  rag: RagConfig;
  models: ModelConfig;
}
