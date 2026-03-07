import { useTranslation } from "react-i18next";

type TranslationParams = Record<string, string | number>;
type TranslationFn = ((key: string, params?: TranslationParams) => string) & {
  raw: (key: string) => unknown;
};

/**
 * Drop-in replacement for next-intl's useTranslations.
 * Uses global i18next resources and keeps existing t()/t.raw() API.
 */
export function useTranslations(namespace: string): TranslationFn {
  const { t: baseT } = useTranslation();

  const t = ((key: string, params?: TranslationParams) => {
    const fullKey = `${namespace}.${key}`;
    const value = baseT(fullKey, { ...params, defaultValue: fullKey }) as unknown;
    if (typeof value === "string") {
      return value === fullKey ? key : value;
    }
    return key;
  }) as TranslationFn;

  t.raw = (key: string): unknown => {
    const fullKey = `${namespace}.${key}`;
    const value = baseT(fullKey, {
      returnObjects: true,
      defaultValue: fullKey,
    });
    if (typeof value === "string" && value === fullKey) {
      return undefined;
    }
    return value;
  };

  return t;
}
