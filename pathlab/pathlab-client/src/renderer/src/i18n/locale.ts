export type AppLanguage = "zh-CN" | "zh-HK" | "en";

const LANGUAGE_STORAGE_KEY = "pathlab_language";

function normalizeLanguage(input?: string | null): AppLanguage {
  if (!input) return "zh-CN";
  const normalized = input.toLowerCase();
  if (normalized.startsWith("zh-tw") || normalized.startsWith("zh-hk") || normalized.includes("hant")) {
    return "zh-HK";
  }
  if (normalized.startsWith("en")) {
    return "en";
  }
  return "zh-CN";
}

export function getCurrentLanguage(): AppLanguage {
  if (typeof window === "undefined") {
    return "zh-CN";
  }
  const stored = window.localStorage.getItem(LANGUAGE_STORAGE_KEY);
  if (stored === "zh-CN" || stored === "zh-HK" || stored === "en") {
    return stored;
  }
  // Migrate old zh-TW preference to zh-HK
  if (stored === "zh-TW") {
    window.localStorage.setItem(LANGUAGE_STORAGE_KEY, "zh-HK");
    return "zh-HK";
  }
  return normalizeLanguage(window.navigator.language);
}

export function setCurrentLanguage(language: AppLanguage) {
  if (typeof window === "undefined") return;
  window.localStorage.setItem(LANGUAGE_STORAGE_KEY, language);
}

export function getBackendLocale(language: AppLanguage = getCurrentLanguage()): "zh-CN" | "en-US" {
  return language === "en" ? "en-US" : "zh-CN";
}

export function getDeepResearchLocale(language: AppLanguage = getCurrentLanguage()): "zh-CN" | "en-US" {
  return getBackendLocale(language);
}

export const languageStorageKey = LANGUAGE_STORAGE_KEY;
