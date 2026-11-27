import { useEffect, useRef, useState } from 'react';
import { ChevronLeft, ChevronRight, Loader2, RotateCw } from 'lucide-react';
import { readWorkbenchPage, type FilePreview } from '../../api/workbench';
import { Button } from '../ui/button';
import { Select } from '../ui/select';
import { useWorkbenchText } from './workbenchText';

export default function DocumentPreview({ preview, workspaceId, initialPage = 1 }: {
  preview: FilePreview;
  workspaceId?: string | null;
  initialPage?: number;
}) {
  const text = useWorkbenchText();
  const total = preview.page_count || 1;
  const [page, setPage] = useState(() => Math.max(1, Math.min(total, initialPage)));
  const [zoom, setZoom] = useState('fit');
  const [source, setSource] = useState(() => initialPage === 1 ? preview.first_page || '' : '');
  const [error, setError] = useState(false);
  const [reload, setReload] = useState(0);
  const previousReload = useRef(0);
  const cache = useRef(new Map<number, string>());
  const pending = useRef(new Map<number, {controller: AbortController; promise: Promise<string>}>());
  const generation = useRef(0);
  const visiblePage = useRef(page);
  visiblePage.current = page;
  const slides = preview.kind === 'slides';
  useEffect(() => {
    const pages = cache.current;
    const requests = pending.current;
    if (preview.first_page) pages.set(1, preview.first_page);
    return () => {
      generation.current++;
      for (const {controller} of requests.values()) controller.abort();
      requests.clear();
      for (const url of pages.values()) if (url.startsWith('blob:')) URL.revokeObjectURL(url);
      pages.clear();
    };
  }, [preview.file_id, preview.revision, workspaceId]);
  function loadPage(number: number): Promise<string> {
    const cached = cache.current.get(number);
    if (cached) return Promise.resolve(cached);
    const existing = pending.current.get(number);
    if (existing) return existing.promise;
    const controller = new AbortController();
    const version = generation.current;
    const promise = readWorkbenchPage(preview.file_id, number, preview.revision, workspaceId, controller.signal).then(blob => {
      if (controller.signal.aborted || version !== generation.current) return '';
      const url = URL.createObjectURL(blob);
      cache.current.set(number, url);
      // Keep the current page and its neighbors; bound browser image memory.
      for (const [key, value] of cache.current) {
        if (cache.current.size <= 3) break;
        if (key === visiblePage.current || key === number) continue;
        cache.current.delete(key);
        if (value.startsWith('blob:')) URL.revokeObjectURL(value);
      }
      return url;
    }).finally(() => {
      if (pending.current.get(number)?.controller === controller) pending.current.delete(number);
    });
    pending.current.set(number, {controller, promise});
    return promise;
  }
  function prefetchNext() {
    if (page < total) void loadPage(page + 1).catch(() => {});
  }
  useEffect(() => { setPage(Math.max(1, Math.min(total, initialPage))); }, [initialPage, total]);
  useEffect(() => {
    let active = true;
    if (reload !== previousReload.current) {
      previousReload.current = reload;
      const old = cache.current.get(page);
      if (old?.startsWith('blob:')) URL.revokeObjectURL(old);
      cache.current.delete(page);
    }
    // Cancel only stale pages, keeping a prefetched next page in flight.
    for (const [number, {controller}] of pending.current) {
      if (number !== page && number !== page + 1) { controller.abort(); pending.current.delete(number); }
    }
    setSource(cache.current.get(page) || '');
    setError(false);
    void loadPage(page).then(url => { if (active && url) setSource(url); }).catch(() => { if (active) setError(true); });
    return () => { active = false; };
  }, [preview.file_id, preview.revision, page, workspaceId, reload]);
  const pageLabel = text(slides ? 'slideNumber' : 'pageNumber').replace('{page}', String(page)).replace('{total}', String(total));
  return <section className="flex h-full min-h-0 min-w-0 flex-col overflow-hidden" aria-label={text(slides ? 'slidePreview' : 'documentPreview')}
    onKeyDown={event => {
      if (event.target instanceof HTMLInputElement || event.target instanceof HTMLButtonElement) return;
      if (event.key === 'ArrowRight' && page < total) { event.preventDefault(); setPage(page + 1); }
      if (event.key === 'ArrowLeft' && page > 1) { event.preventDefault(); setPage(page - 1); }
    }}>
    <div className="flex shrink-0 flex-wrap items-center justify-between gap-2 border-b border-[color:var(--surface-border)] bg-[color:var(--surface-work)] px-3 py-2">
      <div className="flex items-center gap-1">
        <span className="whitespace-nowrap text-xs text-slate-600" aria-live="polite">{pageLabel}</span>
      </div>
      <Select ariaLabel={text('previewZoom')} value={zoom} onChange={setZoom} className="w-32" triggerClassName="text-xs" options={[
        {value: 'fit', label: text('fitPage')}, ...['75','100','125','150','200'].map(value => ({value, label: `${value}%`}))
      ]} />
    </div>
    <div className="relative min-h-0 min-w-0 flex-1">
    <div tabIndex={0} aria-label={pageLabel} className="h-full min-h-0 overflow-auto bg-slate-100/70 px-12 py-3 outline-none focus-visible:ring-2 focus-visible:ring-inset focus-visible:ring-primary-400 sm:px-14">
      {error ? <div role="alert" className="flex h-full flex-col items-center justify-center gap-3 p-5 text-center text-sm text-slate-600">
        <p>{text('previewUnavailable')}</p><Button type="button" variant="outline" size="sm" className="gap-2" onClick={() => setReload(value => value + 1)}><RotateCw size={14} />{text('reloadFile')}</Button>
      </div> : !source ? <div role="status" className="flex h-full items-center justify-center gap-2 text-sm text-slate-500"><Loader2 size={16} className="animate-spin" />{text('loading')}</div>
        : <img src={source} alt={`${preview.name}: ${pageLabel}`} draggable={false} onLoad={prefetchNext}
          className={zoom === 'fit' ? 'mx-auto h-full max-h-full w-full object-contain' : 'mx-auto max-w-none bg-white shadow-sm'}
          style={zoom === 'fit' ? undefined : {width: `${(preview.page_width || 720) * Number(zoom) / 100}px`}} />}
    </div>
    <Button type="button" variant="outline" size="icon" disabled={page === 1} aria-label={text('previousPage')} title={text('previousPage')}
      onClick={() => setPage(page - 1)} className="absolute left-1 top-1/2 z-10 -translate-y-1/2 bg-white/95 shadow-md sm:left-2"><ChevronLeft size={22} aria-hidden="true" /></Button>
    <Button type="button" variant="outline" size="icon" disabled={page >= total} aria-label={text('nextPage')} title={text('nextPage')}
      onClick={() => setPage(page + 1)} className="absolute right-1 top-1/2 z-10 -translate-y-1/2 bg-white/95 shadow-md sm:right-2"><ChevronRight size={22} aria-hidden="true" /></Button>
    </div>
  </section>;
}
