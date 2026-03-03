// API hooks adapted from deep-research for PathLab
import { useEffect, useRef, useState } from "react";

import type { AppConfig } from "../config";
import { useReplay } from "../replay";

import { resolveServiceURL, getAuthHeaders } from "./resolve-service-url";

export function useReplayMetadata() {
  const { isReplay } = useReplay();
  return { title: null, isLoading: { current: false }, hasError: false };
}

const DEFAULT_CONFIG: AppConfig = {
  rag: { provider: "" },
  models: { basic: [], reasoning: [] },
};

export function useConfig(): {
  config: AppConfig;
  loading: boolean;
} {
  const [loading, setLoading] = useState(true);
  const [config, setConfig] = useState<AppConfig>(DEFAULT_CONFIG);

  useEffect(() => {
    const fetchConfig = async () => {
      try {
        const res = await fetch(resolveServiceURL("config"), {
          headers: getAuthHeaders(),
          signal: AbortSignal.timeout(5000),
        });
        if (res.ok) {
          const configData = await res.json();
          setConfig(configData);
        }
      } catch (err) {
        console.warn("[DeepResearch] Failed to fetch config:", err);
      } finally {
        setLoading(false);
      }
    };
    void fetchConfig();
  }, []);

  return { config, loading };
}
