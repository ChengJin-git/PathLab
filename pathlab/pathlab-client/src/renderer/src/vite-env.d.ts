/// <reference types="vite/client" />

interface ImportMetaEnv {
  readonly VITE_API_BASE?: string
  readonly VITE_AI_BASE?: string
  readonly VITE_PREPROCESSING_BASE?: string
  readonly VITE_BASE_PATH?: string
  readonly BASE_URL: string
}

interface ImportMeta {
  readonly env: ImportMetaEnv
}

