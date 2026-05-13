import { useEffect, useRef, useState } from 'react'
import * as pdfjs from 'pdfjs-dist'
import workerUrl from 'pdfjs-dist/build/pdf.worker.min.mjs?url'
import 'pdfjs-dist/web/pdf_viewer.css'

pdfjs.GlobalWorkerOptions.workerSrc = workerUrl

interface PdfViewerProps {
  pdfUrl: string
  refreshKey: number
  scale?: number
  onSelectionChange: (text: string) => void
}

interface PdfLoadState {
  document: pdfjs.PDFDocumentProxy | null
  error: string | null
  loadedPages: number
  totalPages: number
}

interface PdfPageProps {
  document: pdfjs.PDFDocumentProxy
  pageNumber: number
  scale: number
}

function isRenderingCancelled(error: unknown): boolean {
  return error instanceof Error && error.name === 'RenderingCancelledException'
}

function selectionBelongsToRoot(root: HTMLElement, selection: Selection): boolean {
  if (selection.rangeCount === 0 || selection.isCollapsed) return false
  for (let index = 0; index < selection.rangeCount; index += 1) {
    const range = selection.getRangeAt(index)
    if (root.contains(range.commonAncestorContainer)) return true
  }
  return false
}

function PdfPage({ document, pageNumber, scale }: PdfPageProps) {
  const pageRef = useRef<HTMLDivElement>(null)
  const canvasRef = useRef<HTMLCanvasElement>(null)
  const textLayerRef = useRef<HTMLDivElement>(null)
  const [status, setStatus] = useState<'loading' | 'ready' | 'error'>('loading')

  useEffect(() => {
    let cancelled = false
    let renderTask: pdfjs.RenderTask | null = null
    let textLayer: pdfjs.TextLayer | null = null

    async function renderPage() {
      setStatus('loading')
      try {
        const page = await document.getPage(pageNumber)
        if (cancelled || !pageRef.current || !canvasRef.current || !textLayerRef.current) return

        const viewport = page.getViewport({ scale })
        const outputScale = window.devicePixelRatio || 1
        const canvas = canvasRef.current
        const canvasContext = canvas.getContext('2d')
        if (!canvasContext) throw new Error('Could not create PDF canvas context.')

        pageRef.current.style.width = `${viewport.width}px`
        pageRef.current.style.height = `${viewport.height}px`
        canvas.width = Math.floor(viewport.width * outputScale)
        canvas.height = Math.floor(viewport.height * outputScale)
        canvas.style.width = `${viewport.width}px`
        canvas.style.height = `${viewport.height}px`

        textLayerRef.current.replaceChildren()
        textLayerRef.current.style.width = `${viewport.width}px`
        textLayerRef.current.style.height = `${viewport.height}px`
        // PDF.js v4 text-layer spans use `calc(... * var(--scale-factor))`
        // for font-size and offsets. Without this variable, spans collapse
        // to 0 and selection picks the wrong text.
        textLayerRef.current.style.setProperty('--scale-factor', String(viewport.scale))

        renderTask = page.render({
          canvasContext,
          viewport,
          transform: outputScale !== 1 ? [outputScale, 0, 0, outputScale, 0, 0] : undefined,
        })
        await renderTask.promise
        if (cancelled || !textLayerRef.current) return

        const textContent = await page.getTextContent()
        if (cancelled || !textLayerRef.current) return
        textLayer = new pdfjs.TextLayer({
          textContentSource: textContent,
          container: textLayerRef.current,
          viewport,
        })
        await textLayer.render()
        if (!cancelled) setStatus('ready')
      } catch (error) {
        if (!cancelled && !isRenderingCancelled(error)) {
          setStatus('error')
        }
      }
    }

    void renderPage()

    return () => {
      cancelled = true
      renderTask?.cancel()
      textLayer?.cancel()
    }
  }, [document, pageNumber, scale])

  return (
    <div className="flex justify-center">
      <div
        ref={pageRef}
        className="pdf-page relative overflow-hidden rounded-sm bg-white shadow-[0_18px_50px_rgba(15,23,42,0.16)]"
        data-page-number={pageNumber}
      >
        <canvas ref={canvasRef} className="absolute inset-0" aria-label={`PDF page ${pageNumber}`} />
        <div ref={textLayerRef} className="textLayer absolute inset-0" />
        {status === 'loading' ? (
          <div className="absolute inset-0 grid place-items-center bg-white/70 text-xs font-semibold uppercase tracking-[0.16em] text-slate-400">
            Page {pageNumber}
          </div>
        ) : null}
        {status === 'error' ? (
          <div className="absolute inset-0 grid place-items-center bg-red-50 p-4 text-center text-sm text-red-700">
            Failed to render page {pageNumber}.
          </div>
        ) : null}
      </div>
    </div>
  )
}

export function PdfViewer({ pdfUrl, refreshKey, scale = 1, onSelectionChange }: PdfViewerProps) {
  const rootRef = useRef<HTMLDivElement>(null)
  const [state, setState] = useState<PdfLoadState>({
    document: null,
    error: null,
    loadedPages: 0,
    totalPages: 0,
  })

  useEffect(() => {
    let cancelled = false
    let loadedDocument: pdfjs.PDFDocumentProxy | null = null
    const loadingTask = pdfjs.getDocument({ url: pdfUrl })

    loadingTask.onProgress = (progress: pdfjs.OnProgressParameters) => {
      if (!cancelled) {
        setState((current) => ({
          ...current,
          loadedPages: progress.loaded,
          totalPages: progress.total || current.totalPages,
        }))
      }
    }

    setState({ document: null, error: null, loadedPages: 0, totalPages: 0 })
    loadingTask.promise
      .then((document) => {
        loadedDocument = document
        if (!cancelled) {
          setState({
            document,
            error: null,
            loadedPages: document.numPages,
            totalPages: document.numPages,
          })
        }
      })
      .catch((error: unknown) => {
        if (!cancelled) {
          setState({
            document: null,
            error: error instanceof Error ? error.message : String(error),
            loadedPages: 0,
            totalPages: 0,
          })
        }
      })

    return () => {
      cancelled = true
      void loadingTask.destroy()
      void loadedDocument?.destroy()
    }
  }, [pdfUrl, refreshKey])

  const handleMouseUp = () => {
    const root = rootRef.current
    const selection = window.getSelection()
    if (!root || !selection || !selectionBelongsToRoot(root, selection)) return
    const text = selection.toString()
    if (text.trim()) onSelectionChange(text)
  }

  if (state.error) {
    return (
      <div className="rounded-2xl border border-red-200 bg-red-50 p-4 text-sm text-red-700">
        PDF renderer failed: {state.error}
      </div>
    )
  }

  if (!state.document) {
    return (
      <div className="flex h-[72vh] items-center justify-center rounded-2xl bg-slate-100 text-sm text-slate-500">
        Loading PDF document...
      </div>
    )
  }

  return (
    <div
      ref={rootRef}
      onMouseUp={handleMouseUp}
      className="max-h-[72vh] overflow-auto rounded-2xl bg-slate-100 px-4 py-6 shadow-inner"
    >
      <div className="mx-auto flex max-w-fit flex-col gap-6">
        {Array.from({ length: state.document.numPages }, (_, index) => (
          <PdfPage
            key={`${refreshKey}-${scale}-${index + 1}`}
            document={state.document as pdfjs.PDFDocumentProxy}
            pageNumber={index + 1}
            scale={scale}
          />
        ))}
      </div>
    </div>
  )
}
