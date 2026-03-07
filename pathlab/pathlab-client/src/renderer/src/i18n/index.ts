import i18n from "i18next";
import { initReactI18next } from "react-i18next";

import deepResearchEn from "../lib/deep-research/i18n-en.json";
import deepResearchZhCN from "../lib/deep-research/i18n-zh.json";
import deepResearchZhHK from "../lib/deep-research/i18n-zh-HK.json";
import appEn from "./locales/en.json";
import appZhCN from "./locales/zh-CN.json";
import appZhHK from "./locales/zh-HK.json";
import { getCurrentLanguage } from "./locale";

const resources = {
  en: {
    translation: {
      ...deepResearchEn,
      ...appEn,
    },
  },
  "zh-CN": {
    translation: {
      ...deepResearchZhCN,
      ...appZhCN,
    },
  },
  "zh-HK": {
    translation: {
      ...deepResearchZhHK,
      ...appZhHK,
    },
  },
} as const;

void i18n.use(initReactI18next).init({
  resources,
  lng: getCurrentLanguage(),
  fallbackLng: "zh-CN",
  interpolation: {
    escapeValue: false,
  },
  returnNull: false,
});

if (typeof document !== "undefined") {
  document.documentElement.lang = getCurrentLanguage();
}

export default i18n;
