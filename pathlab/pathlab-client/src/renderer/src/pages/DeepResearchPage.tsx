import React, { Suspense } from 'react'
import { Toaster } from 'sonner'

import Main from './DeepResearch/main'

export default function DeepResearchPage() {
  return (
    <div className="flex h-full w-full flex-col overflow-hidden bg-gray-50">
      <Suspense
        fallback={
          <div className="flex h-full w-full items-center justify-center text-gray-500">
            Loading Deep Research...
          </div>
        }
      >
        <Main />
      </Suspense>
      <Toaster />
    </div>
  )
}
