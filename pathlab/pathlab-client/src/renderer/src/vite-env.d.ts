/// <reference types="vite/client" />

interface ImportMetaEnv {
  readonly VITE_API_BASE?: string
  readonly VITE_AI_BASE?: string
  readonly VITE_PREPROCESSING_BASE?: string
  readonly VITE_BASE_PATH?: string
  readonly BASE_URL: string
  // Auto-login configuration (for testing)
  readonly VITE_AUTO_LOGIN?: string
  readonly VITE_TEST_USERNAME?: string
  readonly VITE_TEST_PASSWORD?: string
}

interface ImportMeta {
  readonly env: ImportMetaEnv
}

